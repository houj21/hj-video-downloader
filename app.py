import os
import re
import time
import uuid
import glob
import json
import shutil
import sys
import secrets
import zipfile
import subprocess
import threading
from functools import wraps
from flask import (Flask, request, jsonify, send_file, render_template, Response,
                   stream_with_context, abort, has_request_context, session)

import seo
import seo_content
import seo_geo
import summarizer
import membership
import payments

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


# 把项目内已验证的 yt-dlp 工具函数注入总结模块（避免循环导入）
summarizer.configure(ytdlp=YTDLP, cookie_args=cookie_args, child_env=child_env)


# ==================== 会员账号与支付（会话 / CSRF / 鉴权） ====================

# 会话签名密钥：务必由环境变量注入。缺失时生成一次性随机值（重启后需重新登录），
# 绝不硬编码固定串——历史教训见 docs/AI视频总结-二期设计文档.md §16.3。
APP_SECRET_KEY = (os.environ.get("APP_SECRET_KEY") or "").strip()
SECRET_FROM_ENV = bool(APP_SECRET_KEY)
if not SECRET_FROM_ENV:
    APP_SECRET_KEY = secrets.token_hex(32)

app.secret_key = APP_SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,          # 禁止 JS 读取登录 Cookie
    SESSION_COOKIE_SAMESITE="Lax",         # 挡住大部分跨站请求
    SESSION_COOKIE_SECURE=False,           # 本地 http 开发；站点上 HTTPS 后改为 True
)

membership.init_db()

# 只对这些「改动账号状态」的接口做 CSRF 校验。
# 其余 POST 接口要求 application/json 内容类型，跨站表单无法伪造（需预检），
# 因此不必强制带 token，避免破坏既有前端调用。
CSRF_PROTECTED = ("/api/auth/register", "/api/auth/login",
                  "/api/auth/logout", "/api/checkout")


def current_user():
    """当前登录用户 dict，未登录返回 None。"""
    uid = session.get("uid")
    if not uid:
        return None
    return membership.get_user(uid)


def _me_payload(user):
    if not user:
        return {"logged_in": False, "is_member": False}
    return {
        "logged_in": True,
        "email": user["email"],
        "display": user["email"].split("@")[0],
        "is_member": membership.is_member(user["id"]),
    }


def public_base_url():
    """站点外网地址，用于拼接 Stripe 的 success_url / cancel_url。"""
    return (os.environ.get("PUBLIC_BASE_URL") or "").strip() or request.host_url.rstrip("/")


@app.before_request
def csrf_guard():
    """播种并校验 CSRF Token（双提交：Cookie 会话 + 自定义头）。"""
    if not session.get("csrf"):
        session["csrf"] = secrets.token_urlsafe(32)
    if request.method != "POST":
        return
    path = request.path
    if path.startswith("/api/stripe/"):     # Webhook 靠 Stripe 签名而非 CSRF
        return
    if path not in CSRF_PROTECTED:
        return
    if request.headers.get("X-CSRF-Token", "") != session.get("csrf", ""):
        return jsonify({"error": "页面已过期，请刷新后重试", "code": "csrf_failed"}), 403


@app.context_processor
def inject_account():
    """为所有模板注入登录态与 CSRF Token（不触碰既有 inject_seo_meta）。"""
    return {
        "csrf_token": session.get("csrf", ""),
        "me": _me_payload(current_user()),
        "payments_enabled": payments.configured(),
    }


def membership_required(view):
    """终身会员鉴权装饰器。未登录 401，已登录非会员 403（前端据此渲染升级卡片）。"""
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({
                "error": "该功能为终身会员专属，请先登录",
                "code": "login_required",
                "upgrade_url": "/pricing",
                "logged_in": False,
            }), 401
        if not membership.is_member(user["id"]):
            return jsonify({
                "error": "此功能为终身会员专属",
                "code": "membership_required",
                "upgrade_url": "/pricing",
                "logged_in": True,
            }), 403
        return view(*args, **kwargs)
    return wrapped


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


@app.route("/summarize")
def summarize_page():
    return render_template("summarize.html")


# ==================== SEO / GEO 支持（只新增能力，不改动既有功能） ====================

# 每个语言对应的主行长路径中文为 index.html
TEMPLATES = {
    "zh": {
        "home": "index.html", "summarize": "summarize.html", "pricing": "pricing.html",
        "faq": "faq.html", "guides": "guides.html", "guide": "guide.html",
        "compares": "compares.html", "compare": "compare.html", "landing": "landing.html",
        "404": "404.html",
    },
    "en": {
        "home": "en/home.html", "summarize": "en/summarize.html", "pricing": "en/pricing.html",
        "faq": "en/faq.html", "guides": "en/guides.html", "guide": "en/guide.html",
        "compares": "en/compares.html", "compare": "en/compare.html", "landing": "en/landing.html",
        "404": "en/404.html",
    },
}
EN = seo.EN_PREFIX


@app.context_processor
def inject_seo_meta():
    """为所有模板注入当前页面的 SEO/GEO 元信息（由 seo.py 按请求路径生成）。"""
    path = request.path if has_request_context() else "/"
    meta = seo.meta_for(path)
    lang = meta["lang"]
    return {
        "seo": meta,
        "lang": lang,
        "ui": seo_content.load_ui(lang),
        "answer": meta.get("answer") or {},
        "footer_platforms": platform_links(lang),
        "guide_links": guide_links(lang),
        "compare_links": compare_links(lang),
    }


def _localized(data_list, lang):
    """把数据项的 path 按语言补上前缀，供模板做内链。"""
    out = []
    for item in data_list:
        path = item.get("path")
        if not path:
            continue
        out.append({
            "slug": item.get("slug"),
            "path": (EN + path) if lang == "en" else path,
            "name": item.get("name"),
            "title": item.get("title"),
            "h1": item.get("h1"),
            "description": item.get("description"),
            "tldr": item.get("tldr"),
        })
    return out


def platform_links(lang="zh"):
    """供页脚 / 相关推荐使用的精简平台列表。"""
    return _localized([data for _, data in seo_content.load_platforms(lang)], lang)


def guide_links(lang="zh"):
    return _localized([data for _, data in seo_content.load_guides(lang)], lang)


def compare_links(lang="zh"):
    return _localized([data for _, data in seo_content.load_compares(lang)], lang)


@app.route("/robots.txt")
def robots_txt():
    return Response(seo_geo.robots_txt(), mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    return Response(seo.sitemap_xml(), mimetype="application/xml")


@app.route("/llms.txt")
def llms_txt():
    return Response(seo_geo.llms_txt("zh"), mimetype="text/plain")


@app.route("/llms-full.txt")
def llms_full_txt():
    return Response(seo_geo.llms_full_txt("zh"), mimetype="text/plain")


@app.route(EN + "/llms.txt")
def llms_txt_en():
    return Response(seo_geo.llms_txt("en"), mimetype="text/plain")


@app.route(EN + "/llms-full.txt")
def llms_full_txt_en():
    return Response(seo_geo.llms_full_txt("en"), mimetype="text/plain")


# ---------- 常见问题 ----------

@app.route("/faq")
def faq_page():
    return render_template(TEMPLATES["zh"]["faq"], faq=seo_content.load_faq("zh"))


@app.route(EN + "/faq")
def faq_page_en():
    return render_template(TEMPLATES["en"]["faq"], faq=seo_content.load_faq("en"))


# ---------- 使用指南 ----------

@app.route("/guides")
def guides_index():
    return render_template(
        TEMPLATES["zh"]["guides"],
        index=seo_content.load_guide_index("zh"),
        guides=[data for _, data in seo_content.load_guides("zh")],
        items=[data for _, data in seo_content.load_guides("zh")],
    )


@app.route(EN + "/guides")
def guides_index_en():
    return render_template(
        TEMPLATES["en"]["guides"],
        index=seo_content.load_guide_index("en"),
        guides=[data for _, data in seo_content.load_guides("en")],
        items=[data for _, data in seo_content.load_guides("en")],
    )


@app.route("/guides/<slug>")
def guide_detail(slug):
    return _render_guide(slug, "zh")


@app.route(EN + "/guides/<slug>")
def guide_detail_en(slug):
    return _render_guide(slug, "en")


def _render_guide(slug, lang):
    guides = seo_content.load_guides(lang)
    for _, guide in guides:
        if guide["slug"] == slug:
            related = [data for _, data in guides if data["slug"] != slug][:3]
            return render_template(TEMPLATES[lang]["guide"], g=guide, related=related)
    abort(404)


# ---------- 对比与选型 ----------

@app.route("/compare")
def compares_index():
    return render_template(
        TEMPLATES["zh"]["compares"],
        index=seo_content.load_compare_index("zh"),
        items=[data for _, data in seo_content.load_compares("zh")],
    )


@app.route(EN + "/compare")
def compares_index_en():
    return render_template(
        TEMPLATES["en"]["compares"],
        index=seo_content.load_compare_index("en"),
        items=[data for _, data in seo_content.load_compares("en")],
    )


@app.route("/compare/<slug>")
def compare_detail(slug):
    return _render_compare(slug, "zh")


@app.route(EN + "/compare/<slug>")
def compare_detail_en(slug):
    return _render_compare(slug, "en")


def _render_compare(slug, lang):
    compares = seo_content.load_compares(lang)
    for _, item in compares:
        if item["slug"] == slug:
            related = [data for _, data in compares if data["slug"] != slug][:3]
            return render_template(TEMPLATES[lang]["compare"], c=item, related=related)
    abort(404)


# ---------- 英文版核心页 ----------

@app.route(EN)
def home_en():
    return render_template(TEMPLATES["en"]["home"], platforms=platform_links("en"))


@app.route(EN + "/summarize")
def summarize_page_en():
    return render_template(TEMPLATES["en"]["summarize"])


@app.route(EN + "/pricing")
def pricing_en():
    return render_template(TEMPLATES["en"]["pricing"])


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


# ==================== AI 视频总结 ====================

@app.route("/api/llm/config")
def llm_config():
    """供前端展示当前模型与是否已配置 Key（不回传密钥本身）。"""
    return jsonify({
        "configured": summarizer.llm_configured(),
        "base_url": summarizer.LLM_BASE_URL,
        "model": summarizer.LLM_MODEL,
    })


@app.route("/api/llm/models")
def llm_models():
    """拉取大模型平台可用模型列表，便于挑选 LLM_MODEL 的准确 ID。"""
    try:
        return jsonify({"models": summarizer.list_models(), "current": summarizer.LLM_MODEL})
    except summarizer.SummaryError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/summarize", methods=["POST"])
@membership_required
def start_summary():
    data = request.json or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "请先粘贴视频链接"}), 400
    if not url.startswith("http"):
        return jsonify({"error": "链接格式不正确，请以 http(s) 开头"}), 400

    job_id = uuid.uuid4().hex[:10]
    jobs[job_id] = {
        "kind": "summary",
        "status": "running",
        "stage": "fetching",
        "stage_text": "排队中",
        "percent": 0,
        "url": url,
        "created": time.time(),
    }

    def worker():
        try:
            summarizer.run_summary(jobs[job_id], url)
            jobs[job_id]["status"] = "done"
        except summarizer.SummaryError as exc:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = str(exc)
        except Exception as exc:                      # 兜底：不把堆栈暴露给前端
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = f"总结失败：{type(exc).__name__}"

    thread = threading.Thread(target=worker)
    thread.daemon = True
    thread.start()
    return jsonify({"job_id": job_id})


@app.route("/api/summary/status/<job_id>")
def summary_status(job_id):
    job = jobs.get(job_id)
    if not job or job.get("kind") != "summary":
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status": job["status"],
        "stage": job.get("stage"),
        "stage_text": job.get("stage_text", ""),
        "percent": job.get("percent", 0),
        "error": job.get("error"),
        "meta": job.get("meta"),
        "result": job.get("result"),
        "url": job.get("url"),
    })


@app.route("/api/summary/ask", methods=["POST"])
def summary_ask():
    """基于当前视频上下文追问，SSE 流式返回。"""
    data = request.json or {}
    job = jobs.get((data.get("job_id") or "").strip())
    if not job or job.get("kind") != "summary":
        return jsonify({"error": "任务不存在或已过期，请重新总结"}), 404
    if job.get("status") != "done":
        return jsonify({"error": "总结尚未完成"}), 400

    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "请输入问题"}), 400

    history = data.get("history") or []
    if not isinstance(history, list):
        history = []

    context = summarizer.build_ask_context(job.get("result") or {}, job.get("transcript") or "")
    messages = summarizer.build_ask_messages(question, context, history)

    def stream():
        try:
            for piece in summarizer.chat_stream(messages):
                yield "data: " + json.dumps({"delta": piece}, ensure_ascii=False) + "\n\n"
            yield "data: " + json.dumps({"delta": "", "done": True}, ensure_ascii=False) + "\n\n"
        except summarizer.SummaryError as exc:
            yield "data: " + json.dumps({"error": str(exc)}, ensure_ascii=False) + "\n\n"
        except Exception:
            yield "data: " + json.dumps({"error": "追问失败，请稍后重试"}, ensure_ascii=False) + "\n\n"

    return Response(stream_with_context(stream()), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@app.route("/api/summary/export", methods=["POST"])
def summary_export():
    """导出总结结果：md 直接下载，docx 由后端生成。"""
    data = request.json or {}
    job = jobs.get((data.get("job_id") or "").strip())
    if not job or job.get("kind") != "summary":
        return jsonify({"error": "任务不存在或已过期，请重新总结"}), 404
    if job.get("status") != "done" or not job.get("result"):
        return jsonify({"error": "总结尚未完成，无法导出"}), 400

    fmt = (data.get("format") or "md").strip().lower()
    result = job["result"]
    meta = job.get("meta") or {}
    base = summarizer.safe_filename(meta.get("title") or "视频总结")

    if fmt == "docx":
        try:
            path = summarizer.to_docx(result, meta)
        except summarizer.SummaryError as exc:
            return jsonify({"error": str(exc)}), 500
        except Exception:                             # 兜底：不把堆栈暴露给前端
            return jsonify({"error": "Word 导出失败，可先导出 Markdown"}), 500
        return send_file(path, as_attachment=True, download_name=f"{base}.docx")

    markdown = summarizer.to_markdown(result, meta)
    return Response(
        markdown.encode("utf-8"),
        mimetype="text/markdown; charset=utf-8",
        headers={"Content-Disposition": summarizer.content_disposition(f"{base}.md")},
    )


@app.route("/api/summary/subtitle/<job_id>")
@membership_required
def summary_subtitle(job_id):
    """字幕文本 Tab 的数据源：懒加载时间轴，避免把上千条字幕塞进 status 轮询。"""
    job = jobs.get(job_id)
    if not job or job.get("kind") != "summary":
        return jsonify({"error": "任务不存在或已过期，请重新总结"}), 404
    cues = job.get("cues") or []
    return jsonify({
        "cues": [{
            "start": c.get("start", 0),
            "end": c.get("end", 0),
            "text": c.get("text", ""),
        } for c in cues],
    })


@app.route("/api/summary/subtitle", methods=["POST"])
@membership_required
def summary_subtitle_download():
    """字幕下载：txt（速读）/ srt（带时间轴，可导入播放器）。"""
    data = request.json or {}
    job = jobs.get((data.get("job_id") or "").strip())
    if not job or job.get("kind") != "summary":
        return jsonify({"error": "任务不存在或已过期，请重新总结"}), 404

    cues = job.get("cues") or []
    if not cues:
        return jsonify({"error": "该视频暂无可用字幕"}), 400

    fmt = (data.get("format") or "txt").strip().lower()
    if fmt not in ("txt", "srt"):
        return jsonify({"error": "不支持的字幕格式"}), 400

    body = summarizer.cues_to_srt(cues) if fmt == "srt" else summarizer.cues_to_txt(cues)
    base = summarizer.safe_filename((job.get("meta") or {}).get("title") or "视频字幕")
    return Response(
        body.encode("utf-8"),
        mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": summarizer.content_disposition(f"{base}字幕.{fmt}")},
    )


# ==================== 会员账号 / 下单 / 支付回调 ====================

_auth_hits = {}
_auth_lock = threading.Lock()


def rate_limited(key, limit=10, window=60):
    """极简内存限流（按 IP / 用户），只用于注册、登录、下单，防脚本刷接口。"""
    now = time.time()
    with _auth_lock:
        if len(_auth_hits) > 5000:          # 兜底防内存膨胀
            _auth_hits.clear()
        bucket = [t for t in _auth_hits.get(key, []) if now - t < window]
        if len(bucket) >= limit:
            _auth_hits[key] = bucket
            return True
        bucket.append(now)
        _auth_hits[key] = bucket
        return False


def client_ip():
    return (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()


def _safe_next(raw):
    """登录后跳转地址：只允许站内相对路径，挡掉 open redirect。"""
    if not raw or not raw.startswith("/") or raw.startswith("//"):
        return ""
    return raw


def _obj_get(obj, key, default=None):
    """兼容 stripe 对象与普通 dict 的字段读取。"""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    value = getattr(obj, key, default)
    return default if value is None else value


@app.route("/account")
def account_page():
    return render_template("account.html", next_url=_safe_next(request.args.get("next") or ""))


@app.route("/api/auth/register", methods=["POST"])
def auth_register():
    if rate_limited("reg:" + client_ip(), limit=8):
        return jsonify({"error": "操作过于频繁，请稍后再试"}), 429
    data = request.get_json(silent=True) or {}
    try:
        user = membership.create_user(data.get("email", ""), data.get("password", ""))
    except membership.MembershipError as exc:
        return jsonify({"error": str(exc)}), 400

    session.clear()                          # 防会话固定：登录成功即换新会话
    session["uid"] = user["id"]
    session["csrf"] = secrets.token_urlsafe(32)
    return jsonify({"ok": True, "email": user["email"], "is_member": False})


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    if rate_limited("login:" + client_ip(), limit=10):
        return jsonify({"error": "尝试过于频繁，请稍后再试"}), 429
    data = request.get_json(silent=True) or {}
    try:
        user = membership.verify_user(data.get("email", ""), data.get("password", ""))
    except membership.MembershipError as exc:
        return jsonify({"error": str(exc)}), 400

    session.clear()
    session["uid"] = user["id"]
    session["csrf"] = secrets.token_urlsafe(32)
    return jsonify({
        "ok": True,
        "email": user["email"],
        "is_member": membership.is_member(user["id"]),
    })


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me")
def api_me():
    return jsonify(_me_payload(current_user()))


@app.route("/api/checkout", methods=["POST"])
def api_checkout():
    """创建（或复用）Checkout Session。重复点击只会拿到同一个收银台链接。"""
    user = current_user()
    if not user:
        return jsonify({"error": "请先登录后再开通会员", "code": "login_required",
                        "login_url": "/account"}), 401
    if rate_limited("checkout:" + user["id"], limit=10):
        return jsonify({"error": "操作过于频繁，请稍后再试"}), 429

    data = request.get_json(silent=True) or {}
    try:
        plan = payments.get_plan(data.get("plan", ""))
    except membership.MembershipError as exc:
        return jsonify({"error": str(exc)}), 400

    if not payments.configured():
        return jsonify({"error": "支付通道尚未配置，请联系站长"}), 503

    # 幂等第一层：已付过款就不要再建单
    if membership.has_paid_order(user["id"], plan["code"]) or membership.is_member(user["id"]):
        return jsonify({"error": "你已是终身会员，无需重复购买", "code": "already_member"}), 409

    order = membership.find_reusable_order(user["id"], plan["code"])
    if not order:
        order_id = membership.create_order(user["id"], plan["code"],
                                          plan["amount"], plan["currency"])
        order = membership.get_order(order_id)

    try:
        session_id, checkout_url = payments.ensure_checkout_session(
            order, user["email"], public_base_url())
    except payments.PaymentsError as exc:
        return jsonify({"error": str(exc)}), 502

    if not checkout_url:
        return jsonify({"error": "未能获取支付链接，请稍后重试"}), 502
    if not order.get("stripe_session_id"):
        membership.attach_session(order["id"], session_id, checkout_url)
    return jsonify({"order_id": order["id"], "checkout_url": checkout_url})


@app.route("/api/order/<order_id>")
def api_order(order_id):
    """订单状态查询（成功页轮询）。必须校验订单归属，杜绝越权开通。"""
    user = current_user()
    if not user:
        return jsonify({"error": "请先登录", "code": "login_required"}), 401
    if not membership.order_belongs_to(order_id, user["id"]):
        return jsonify({"error": "订单不存在"}), 404

    order = membership.get_order(order_id)

    # 兜底同步：Webhook 可能因本地未开隧道而缺席，浏览器可主动向 Stripe 查询一次
    if (order["status"] == membership.ORDER_PENDING
            and order.get("stripe_session_id")
            and request.args.get("sync") == "1"):
        try:
            stripe_session = payments.retrieve_session(order["stripe_session_id"])
            if (_obj_get(stripe_session, "payment_status") == "paid"
                    and payments.session_amount_matches(stripe_session, order)):
                membership.try_mark_paid(
                    order["id"],
                    order["stripe_session_id"],
                    _payment_intent_id(_obj_get(stripe_session, "payment_intent")),
                    None,
                )
                order = membership.get_order(order_id)
        except payments.PaymentsError:
            pass                                  # 查询失败不影响前端继续轮询

    return jsonify({
        "order_id": order["id"],
        "status": order["status"],
        "plan": order["plan"],
        "amount": order["amount"],
        "currency": order["currency"],
        "paid": order["status"] == membership.ORDER_PAID,
        "is_member": membership.is_member(user["id"]),
    })


def _payment_intent_id(value):
    if not value:
        return None
    if isinstance(value, str):
        return value
    return _obj_get(value, "id")


@app.route("/api/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """Stripe 回调：验签 → 事件去重 → 事务发货。是会员生效的唯一可信来源。"""
    if not payments.webhook_configured():
        return jsonify({"error": "webhook not configured"}), 503

    raw = request.get_data()                  # 必须是原始字节，不能重新序列化
    signature = request.headers.get("Stripe-Signature", "")
    try:
        event = payments.parse_webhook(raw, signature)
    except payments.PaymentsError as exc:
        print(f"[HJ][stripe] Webhook 拒绝：{exc}")
        return jsonify({"error": "invalid signature"}), 400

    event_type = _obj_get(event, "type", "")
    event_id = _obj_get(event, "id", "")
    if event_type not in membership.SUPPORTED_EVENTS:
        return jsonify({"received": True, "ignored": True})

    try:
        stripe_session = _obj_get(_obj_get(event, "data", {}), "object")
        session_id = _obj_get(stripe_session, "id", "")
        order = membership.get_order_by_session(session_id)
        if not order:
            # 极端竞态：Session 已建但 session_id 尚未回写库，用 client_reference_id 兜底
            order = membership.get_order(_obj_get(stripe_session, "client_reference_id", ""))
            if order and not order.get("stripe_session_id"):
                membership.attach_session(order["id"], session_id,
                                          _obj_get(stripe_session, "url"))
        if not order:
            return jsonify({"received": True, "unknown_order": True})

        if event_type in ("checkout.session.expired", "checkout.session.async_payment_failed"):
            membership.mark_expired(order["id"])
            return jsonify({"received": True})

        # 金额二次校验：后台价格配错时宁可不发货，也不产生错账
        if not payments.session_amount_matches(stripe_session, order):
            print(f"[HJ][stripe] 金额不匹配，拒绝发货 order={order['id']} "
                  f"expected={order['amount']} got={_obj_get(stripe_session, 'amount_total')}")
            return jsonify({"received": True, "amount_mismatch": True})

        granted = membership.try_mark_paid(
            order["id"],
            session_id,
            _payment_intent_id(_obj_get(stripe_session, "payment_intent")),
            event_id,
        )
        print(f"[HJ][stripe] {event_type} order={order['id']} 首次发货={granted}")
        return jsonify({"received": True, "granted": granted})
    except Exception as exc:                  # 返回 5xx 让 Stripe 重试，幂等由上面保证
        print(f"[HJ][stripe] Webhook 处理异常：{type(exc).__name__}")
        return jsonify({"error": "webhook handler failed"}), 500


@app.route("/pay/success")
def pay_success():
    return render_template("pay_success.html", order_id=request.args.get("order") or "")


@app.route("/pay/cancel")
def pay_cancel():
    return render_template("pay_success.html", order_id="", canceled=True)


def register_platform_pages():
    """按 data/seo*/platforms 下的数据文件注册长尾落地页路由（中英双语）。"""
    for lang in ("zh", "en"):
        platforms = dict(seo_content.load_platforms(lang))
        template = TEMPLATES[lang]["landing"]
        for slug, data in platforms.items():
            base_path = data.get("path") or ("/%s-video-download" % slug)
            full_path = (EN + base_path) if lang == "en" else base_path
            related_links = [
                {
                    "name": platforms[key].get("name"),
                    "title": platforms[key].get("title"),
                    "path": (EN if lang == "en" else "") + (platforms[key].get("path") or ""),
                }
                for key in data.get("related", []) if key in platforms
            ]

            def view(slug=slug, related_links=related_links, template=template, lang=lang):
                page = dict(seo_content.load_platforms(lang))[slug]
                return render_template(template, p=page, related=related_links)

            app.add_url_rule(full_path, "platform_%s_%s" % (lang, slug), view)


register_platform_pages()


@app.errorhandler(404)
def page_not_found(error):
    """404 返回友好页面；API 路径保持原来的 JSON 行为不变。"""
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found"}), 404
    lang = seo.detect_lang(request.path)
    return render_template(TEMPLATES[lang]["404"]), 404


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
    # 输出编码兜底：挂真实控制台时 Python 走 Unicode 通道没问题，
    # 但一旦 stdout 被重定向到文件/管道（后台服务、日志采集），Windows 默认回退到 GBK，
    # 日志里的 ¥、中文会直接 UnicodeEncodeError 让服务起不来。
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    port = int(os.environ.get("PORT", 8899))
    host = os.environ.get("HOST", "127.0.0.1")
    update_ytdlp()
    if os.path.isfile(COOKIE_FILE):
        print(f"[HJ] 使用 Cookie 文件: {COOKIE_FILE}")
    print(f"[HJ] 下载目录: {DOWNLOAD_DIR}（{FILE_TTL // 60} 分钟后自动清理）")
    if summarizer.llm_configured():
        print(f"[HJ] AI 总结已启用: {summarizer.LLM_MODEL} @ {summarizer.LLM_BASE_URL}")
    else:
        print("[HJ] AI 总结未配置 LLM_API_KEY，总结页将显示配置指引（参考 llm_config.example.bat）")
    print(f"[HJ] 会员数据库: {membership.DB_PATH}")
    if not SECRET_FROM_ENV:
        print("[HJ] 警告：未设置 APP_SECRET_KEY，本次使用临时随机密钥（重启后需重新登录）")
    if payments.configured():
        print(f"[HJ] Stripe 支付已启用：终身会员 ¥{payments.AMOUNT / 100:.2f} "
              f"{payments.CURRENCY.upper()}（{'测试密钥' if payments.SECRET_KEY.startswith('sk_test_') else '生产密钥'}）")
        if not payments.webhook_configured():
            print("[HJ] 警告：未配置 STRIPE_WEBHOOK_SECRET，支付回调将无法验签（会员不会自动开通）")
        else:
            print("[HJ] Webhook 签名密钥已配置，回调地址：/api/stripe/webhook")
    else:
        print("[HJ] Stripe 未配置：定价页会提示支付通道未开启（参考 stripe_config.example.bat）")
    print(f"[HJ] 服务已启动: http://{host}:{port}")
    app.run(host=host, port=port)
