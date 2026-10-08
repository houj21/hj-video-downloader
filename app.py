import os
import re
import time
import uuid
import glob
import json
import shutil
import sys
import zipfile
import subprocess
import threading
from flask import Flask, request, jsonify, send_file, render_template

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ---- tuning (all overridable by environment variables) ----
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", 3))       # parallel downloads
FILE_TTL = int(os.environ.get("FILE_TTL", 1800))                # keep files 30 min
JOB_TTL = int(os.environ.get("JOB_TTL", 3600))                  # keep job records 1 h
CLEAN_INTERVAL = int(os.environ.get("CLEAN_INTERVAL", 300))     # sweep every 5 min
MAX_DIR_BYTES = int(os.environ.get("MAX_DIR_BYTES", 2 * 1024 ** 3))  # 2 GB cap
DOWNLOAD_TIMEOUT = int(os.environ.get("DOWNLOAD_TIMEOUT", 900))  # 15 min per job

# Optional cookies.txt next to app.py (or COOKIE_FILE env) for login-only sources
COOKIE_FILE = os.environ.get("COOKIE_FILE") or os.path.join(BASE_DIR, "cookies.txt")

PERCENT_RE = re.compile(r"([\d.]+)%")


def resolve_ytdlp():
    """Locate yt-dlp (PATH first, then the active venv, then `python -m yt_dlp`)."""
    found = shutil.which("yt-dlp")
    if found:
        return [found]
    candidate = os.path.join(sys.prefix, "Scripts", "yt-dlp.exe") if os.name == "nt" \
        else os.path.join(sys.prefix, "bin", "yt-dlp")
    if os.path.isfile(candidate):
        return [candidate]
    return [sys.executable, "-m", "yt_dlp"]


YTDLP = resolve_ytdlp()

jobs = {}
download_slots = threading.Semaphore(MAX_CONCURRENT)


def cookie_args():
    """Append --cookies when a cookies.txt is provided (login-only sources)."""
    if COOKIE_FILE and os.path.isfile(COOKIE_FILE):
        return ["--cookies", COOKIE_FILE]
    return []


def child_env():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def progress_cmd(cmd):
    """Make yt-dlp emit newline-separated progress we can parse line by line."""
    return cmd + ["--no-colors", "--newline",
                  "--progress-template", "%(progress._percent_str)s"]


def track_progress(proc, job, span_start=0.0, span_size=1.0):
    """Read yt-dlp progress lines and write a 0-100 percent onto the job."""
    for line in proc.stdout:
        m = PERCENT_RE.search(line)
        if not m:
            continue
        try:
            value = float(m.group(1))
        except ValueError:
            continue
        job["percent"] = round(span_start + value / 100.0 * span_size, 1)


def parse_ytdlp_json(stdout):
    """Parse yt-dlp JSON output.

    With ``-j`` yt-dlp prints one JSON object per line. Some extractors
    emit multiple videos even with ``--no-playlist``, so stdout contains
    several objects and a plain ``json.loads`` raises "Extra data".
    Return the first valid object.
    """
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        return json.loads(line)
    raise ValueError("yt-dlp returned no data")


def format_args(format_choice, format_id):
    if format_choice == "audio":
        return ["-x", "--audio-format", "mp3"]
    if format_id:
        return ["-f", f"{format_id}+bestaudio/best", "--merge-output-format", "mp4"]
    return ["-f", "bestvideo+bestaudio/best", "--merge-output-format", "mp4"]


def run_ytdlp(cmd, job, span_start=0.0, span_size=100.0):
    """Run yt-dlp, streaming progress onto the job. Returns True on success."""
    proc = subprocess.Popen(
        progress_cmd(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=child_env(),
    )
    track_progress(proc, job, span_start, span_size)

    try:
        proc.wait(timeout=DOWNLOAD_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        job["status"] = "error"
        job["error"] = f"下载超时（{DOWNLOAD_TIMEOUT // 60} 分钟限制）"
        return False

    if proc.returncode != 0:
        stderr = (proc.stderr.read() or "").strip()
        job["status"] = "error"
        job["error"] = stderr.split("\n")[-1] if stderr else "下载失败"
        return False
    return True


def run_download(job_id, url, format_choice, format_id):
    job = jobs[job_id]
    out_template = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")

    cmd = YTDLP + ["--no-playlist", "-o", out_template] + cookie_args()
    cmd += format_args(format_choice, format_id)
    cmd.append(url)

    with download_slots:
        try:
            if not run_ytdlp(cmd, job):
                return

            files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{job_id}.*"))
            if not files:
                job["status"] = "error"
                job["error"] = "下载完成但未找到文件"
                return

            if format_choice == "audio":
                target = [f for f in files if f.endswith(".mp3")]
                chosen = target[0] if target else files[0]
            else:
                target = [f for f in files if f.endswith(".mp4")]
                chosen = target[0] if target else files[0]

            for f in files:
                if f != chosen:
                    try:
                        os.remove(f)
                    except OSError:
                        pass

            job["status"] = "done"
            job["percent"] = 100
            job["file"] = chosen
            ext = os.path.splitext(chosen)[1]
            title = job.get("title", "").strip()
            # Sanitize title for filename (Windows-illegal chars)
            if title:
                safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()[:100].strip()
                job["filename"] = f"{safe_title}{ext}" if safe_title else os.path.basename(chosen)
            else:
                job["filename"] = os.path.basename(chosen)
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)


def run_batch(job_id, urls, format_choice, format_id):
    """Download several videos into one folder and serve them as a single zip."""
    job = jobs[job_id]
    batch_dir = os.path.join(DOWNLOAD_DIR, f"batch_{job_id}")
    os.makedirs(batch_dir, exist_ok=True)
    total = max(len(urls), 1)

    with download_slots:
        try:
            for index, url in enumerate(urls):
                job["current"] = index + 1
                span_start = index * 100.0 / total
                cmd = YTDLP + ["--no-playlist", "-o",
                               os.path.join(batch_dir, f"{index + 1:02d}.%(ext)s")] + cookie_args()
                cmd += format_args(format_choice, format_id)
                cmd.append(url)
                if not run_ytdlp(cmd, job, span_start, 100.0 / total):
                    shutil.rmtree(batch_dir, ignore_errors=True)
                    return

            files = [f for f in glob.glob(os.path.join(batch_dir, "*")) if os.path.isfile(f)]
            if not files:
                job["status"] = "error"
                job["error"] = "批量下载完成但未找到文件"
                shutil.rmtree(batch_dir, ignore_errors=True)
                return

            zip_path = os.path.join(DOWNLOAD_DIR, f"{job_id}.zip")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in files:
                    zf.write(f, arcname=os.path.basename(f))
            shutil.rmtree(batch_dir, ignore_errors=True)

            job["status"] = "done"
            job["percent"] = 100
            job["file"] = zip_path
            job["filename"] = f"HJ批量下载_{len(files)}个文件.zip"
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)
            shutil.rmtree(batch_dir, ignore_errors=True)


def cleanup_once():
    """Delete expired download files and stale job records; enforce the size cap."""
    now = time.time()

    for path in glob.glob(os.path.join(DOWNLOAD_DIR, "*")):
        try:
            if now - os.path.getmtime(path) > FILE_TTL:
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    os.remove(path)
        except OSError:
            pass

    files = []
    for path in glob.glob(os.path.join(DOWNLOAD_DIR, "*")):
        if os.path.isfile(path):
            try:
                files.append((os.path.getmtime(path), os.path.getsize(path), path))
            except OSError:
                pass

    total = sum(size for _, size, _ in files)
    if total > MAX_DIR_BYTES:
        for _, size, path in sorted(files):
            if total <= MAX_DIR_BYTES:
                break
            try:
                os.remove(path)
                total -= size
            except OSError:
                pass

    for job_id in list(jobs.keys()):
        job = jobs[job_id]
        if now - job.get("created", now) > JOB_TTL:
            if job.get("status") == "done":
                try:
                    os.remove(job["file"])
                except (OSError, KeyError):
                    pass
            jobs.pop(job_id, None)


def cleanup_worker():
    while True:
        time.sleep(CLEAN_INTERVAL)
        try:
            cleanup_once()
        except Exception:
            pass


threading.Thread(target=cleanup_worker, daemon=True).start()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/pricing")
def pricing():
    return render_template("pricing.html")


@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    cmd = YTDLP + ["--no-playlist", "-j"] + cookie_args() + [url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return jsonify({"error": result.stderr.strip().split("\n")[-1]}), 400

        info = parse_ytdlp_json(result.stdout)

        # Build quality options — keep best format per resolution
        best_by_height = {}
        for f in info.get("formats", []):
            height = f.get("height")
            if height and f.get("vcodec", "none") != "none":
                tbr = f.get("tbr") or 0
                if height not in best_by_height or tbr > (best_by_height[height].get("tbr") or 0):
                    best_by_height[height] = f

        formats = []
        for height, f in best_by_height.items():
            formats.append({
                "id": f["format_id"],
                "label": f"{height}p",
                "height": height,
            })
        formats.sort(key=lambda x: x["height"], reverse=True)

        return jsonify({
            "title": info.get("title", ""),
            "thumbnail": info.get("thumbnail", ""),
            "duration": info.get("duration"),
            "uploader": info.get("uploader", ""),
            "formats": formats,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out fetching video info"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/playlist", methods=["POST"])
def get_playlist_info():
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    cmd = YTDLP + ["--flat-playlist", "-J"] + cookie_args() + [url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return jsonify({"error": result.stderr.strip().split("\n")[-1]}), 400

        info = json.loads(result.stdout)
        entries = info.get("entries", [])
        urls = [entry.get("url") for entry in entries if entry.get("url")]
        return jsonify({"urls": urls})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out fetching playlist info"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.json
    url = data.get("url", "").strip()
    urls = [u.strip() for u in (data.get("urls") or [])
            if isinstance(u, str) and u.strip().startswith("http")]
    format_choice = data.get("format", "video")
    format_id = data.get("format_id")
    title = data.get("title", "")

    if not url and not urls:
        return jsonify({"error": "No URL provided"}), 400

    batch = bool(urls)
    job_id = uuid.uuid4().hex[:10]
    jobs[job_id] = {
        "status": "downloading",
        "url": url or (urls[0] if urls else ""),
        "title": title,
        "percent": 0,
        "created": time.time(),
    }

    if batch:
        target = run_batch
        args = (job_id, urls, format_choice, format_id)
        jobs[job_id]["total"] = len(urls)
        jobs[job_id]["current"] = 0
    else:
        target = run_download
        args = (job_id, url, format_choice, format_id)

    thread = threading.Thread(target=target, args=args)
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id, "batch": batch})


@app.route("/api/status/<job_id>")
def check_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status": job["status"],
        "error": job.get("error"),
        "filename": job.get("filename"),
        "percent": job.get("percent"),
        "current": job.get("current"),
        "total": job.get("total"),
    })


@app.route("/api/file/<job_id>")
def download_file(job_id):
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        return jsonify({"error": "File not ready"}), 404
    return send_file(job["file"], as_attachment=True, download_name=job["filename"])


def update_ytdlp():
    """Keep extractors fresh; silently skip when offline (or SKIP_YTDLP_UPDATE=1)."""
    if os.environ.get("SKIP_YTDLP_UPDATE") == "1":
        return
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "yt-dlp"],
                       timeout=180, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8899))
    host = os.environ.get("HOST", "127.0.0.1")
    update_ytdlp()
    if os.path.isfile(COOKIE_FILE):
        print(f"[HJ] 使用 Cookie 文件: {COOKIE_FILE}")
    print(f"[HJ] 下载目录: {DOWNLOAD_DIR}（{FILE_TTL // 60} 分钟后自动清理）")
    print(f"[HJ] 服务已启动: http://{host}:{port}")
    app.run(host=host, port=port)
