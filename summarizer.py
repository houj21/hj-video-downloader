"""AI 视频总结模块：字幕抓取 / 解析 / 大模型总结 / 追问 / 导出。

设计要点见 docs/AI视频总结-设计文档.md。
本模块不依赖 app.py，可被单独导入做单元自测；app.py 通过 configure()
把 yt-dlp 相关工具函数注入进来，避免循环导入。
"""

import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# --------------------------------------------------------------------------
# 配置（全部可用环境变量覆盖）
# --------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 默认接入「新疆幻城网安科技公益大模型安全网关」（NewAPI，OpenAI 兼容）
#   平台：https://api.hcnsec.cn/   控制台：https://api.hcnsec.cn/console
#   BaseURL：https://api.hcnsec.cn/v1   鉴权：Authorization: Bearer sk-xxx
# 换成任意 OpenAI 兼容服务只需改 LLM_BASE_URL / LLM_MODEL 两个环境变量。
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.hcnsec.cn/v1").strip()
LLM_API_KEY = os.environ.get("LLM_API_KEY", "").strip()
# auto = 平台智能路由（一定可用）。想固定模型请填「模型广场」里的准确 ID，
# 例如 deepseek-v3.2 / deepseek-v4-pro / glm-5.1 / qwen3.6-plus / kimi-k2.6
LLM_MODEL = os.environ.get("LLM_MODEL", "auto").strip()
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", 180))
# 网关文档提示：max_tokens 过小会导致总结被截断，默认给足
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", 8192))

SUMMARY_CHUNK_CHARS = int(os.environ.get("SUMMARY_CHUNK_CHARS", 60000))
SUMMARY_MAX_CONCURRENCY = int(os.environ.get("SUMMARY_MAX_CONCURRENCY", 3))
ASK_CONTEXT_CHARS = int(os.environ.get("ASK_CONTEXT_CHARS", 60000))
# 网关偶发中途断连（RemoteDisconnected）时的自动重试：次数 + 退避基数（秒）
LLM_RETRY_ATTEMPTS = int(os.environ.get("LLM_RETRY_ATTEMPTS", 3))
LLM_RETRY_DELAY = float(os.environ.get("LLM_RETRY_DELAY", 2.0))

SUB_LANGS = os.environ.get("SUB_LANGS", "zh-Hans,zh-CN,zh,zh-TW,en.*")
COOKIE_FILE = os.environ.get("COOKIE_FILE") or os.path.join(BASE_DIR, "cookies.txt")

_llm_slots = threading.Semaphore(max(1, SUMMARY_MAX_CONCURRENCY))


class SummaryError(Exception):
    """可安全回传给前端的业务错误（不含本地路径与堆栈）。"""


# --------------------------------------------------------------------------
# 由 app.py 注入的 yt-dlp 工具（未注入时使用内置兜底实现，便于独立测试）
# --------------------------------------------------------------------------

_YTDLP = None
_COOKIE_ARGS_FN = None
_CHILD_ENV_FN = None


def configure(ytdlp=None, cookie_args=None, child_env=None):
    """app.py 启动时调用，注入项目内已验证的 yt-dlp 工具函数。"""
    global _YTDLP, _COOKIE_ARGS_FN, _CHILD_ENV_FN
    _YTDLP = ytdlp or _YTDLP
    _COOKIE_ARGS_FN = cookie_args or _COOKIE_ARGS_FN
    _CHILD_ENV_FN = child_env or _CHILD_ENV_FN


def _resolve_ytdlp():
    if _YTDLP:
        return list(_YTDLP)
    found = shutil.which("yt-dlp")
    if found:
        return [found]
    candidate = os.path.join(sys.prefix, "Scripts", "yt-dlp.exe") if os.name == "nt" \
        else os.path.join(sys.prefix, "bin", "yt-dlp")
    if os.path.isfile(candidate):
        return [candidate]
    return [sys.executable, "-m", "yt_dlp"]


def _cookie_args():
    if _COOKIE_ARGS_FN:
        return list(_COOKIE_ARGS_FN())
    return ["--cookies", COOKIE_FILE] if os.path.isfile(COOKIE_FILE) else []


def _child_env():
    if _CHILD_ENV_FN:
        return _CHILD_ENV_FN()
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return env


# --------------------------------------------------------------------------
# 通用工具
# --------------------------------------------------------------------------

_ILLEGAL_CHARS = r'\/:*?"<>|'


def safe_filename(name, limit=80):
    """沿用项目既有规则：过滤 Windows 非法字符并截断。"""
    cleaned = "".join(c for c in (name or "") if c not in _ILLEGAL_CHARS).strip()
    return cleaned[:limit].strip() or "视频总结"


def fmt_ts(seconds):
    """秒 -> mm:ss / hh:mm:ss。"""
    try:
        seconds = max(0, int(round(float(seconds))))
    except (TypeError, ValueError):
        return "00:00"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def llm_configured():
    return bool(LLM_API_KEY)


def content_disposition(filename):
    """生成 RFC 6266 的 Content-Disposition 值。

    HTTP 头按 latin-1 编码，直接塞中文文件名会让 Werkzeug 抛 UnicodeEncodeError
    并断开连接（中文标题视频导出会直接失败）。因此必须给出 ASCII 回退名，
    再用 filename*=UTF-8''<百分号编码> 提供真实文件名。
    """
    from urllib.parse import quote

    ascii_name = re.sub(r"[^\x20-\x7E]", "", filename).strip().replace('"', "")
    # 纯中文名过滤后可能只剩 ".srt"，需要保证 ASCII 回退名可读
    if not ascii_name or ascii_name.startswith("."):
        ext = os.path.splitext(filename)[1] or ".md"
        ascii_name = "video-summary" + ext
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename)}'


# --------------------------------------------------------------------------
# 字幕抓取（只拉字幕轨，不下载视频）
# --------------------------------------------------------------------------

def fetch_meta(url, timeout=90):
    """用 yt-dlp -j 取视频元信息（标题/时长/上传者/封面）。"""
    cmd = _resolve_ytdlp() + ["--no-playlist", "-j"] + _cookie_args() + [url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace",
                                timeout=timeout, env=_child_env())
    except subprocess.TimeoutExpired:
        raise SummaryError("视频信息获取超时，请稍后重试")
    except FileNotFoundError:
        raise SummaryError("未找到 yt-dlp，请先运行 run.bat 安装依赖")

    if result.returncode != 0:
        raise SummaryError(_last_error(result.stderr, "无法解析该链接"))

    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            info = json.loads(line)
        except json.JSONDecodeError:
            continue
        return {
            "title": info.get("title") or "",
            "thumbnail": info.get("thumbnail") or "",
            "duration": info.get("duration"),
            "uploader": info.get("uploader") or "",
            "webpage_url": info.get("webpage_url") or url,
        }
    raise SummaryError("未能读取视频信息，请确认链接是否正确")


def _last_error(stderr, fallback):
    """只取 yt-dlp 最后一行错误摘要，避免把本地路径与堆栈暴露到前端。"""
    text = (stderr or "").strip()
    if not text:
        return fallback
    return text.splitlines()[-1].strip()[:200] or fallback


def _run_subtitle_cmd(url, out_dir, langs):
    out_template = os.path.join(out_dir, "sub.%(ext)s")
    # 注意：不要加 --no-warnings——B站/YouTube 的「需要登录」「人机校验」提示以 WARNING
    # 形式输出在 stderr，保留它们才能给用户准确的失败原因（见 _no_subtitle_reason）。
    cmd = _resolve_ytdlp() + [
        "--skip-download", "--no-playlist",
        "--write-subs", "--write-auto-subs",
        "--sub-langs", langs,
        "--sub-format", "vtt/srt/best",
        "--convert-subs", "srt",
        "-o", out_template,
    ] + _cookie_args() + [url]
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          timeout=180, env=_child_env())


def fetch_subtitle(url, timeout=180):
    """抓取字幕，返回 (字幕文件路径, 元信息)。抓不到时抛 NoSubtitleError。"""
    meta = fetch_meta(url)

    work_dir = tempfile.mkdtemp(prefix="hjsub_")
    diagnostics = []
    try:
        # 首选中文轨；拿不到再退化为全部语言
        for langs in (SUB_LANGS, "all"):
            try:
                proc = _run_subtitle_cmd(url, work_dir, langs)
            except subprocess.TimeoutExpired:
                diagnostics.append("字幕抓取超时")
                continue
            except FileNotFoundError:
                raise SummaryError("未找到 yt-dlp，请先运行 run.bat 安装依赖")
            diagnostics.append((proc.stderr or "") + (proc.stdout or ""))
            found = _find_subtitle(work_dir)
            if found:
                return found, meta
            if langs != "all":
                _clear_dir(work_dir)

        raise SummaryError(_no_subtitle_reason("\n".join(diagnostics)))
    except SummaryError:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise


def _no_subtitle_reason(log):
    """区分「真的没字幕」和「需要登录 / 被风控 / 网络问题」，给出可操作提示。

    实测（2026-10）：B站未登录时 yt-dlp 提示 “Subtitles are only available when
    logged in”；YouTube 常提示 “Sign in to confirm you're not a bot”。这类情况
    如果统一报「没有字幕」会严重误导用户。
    """
    text = (log or "").lower()
    if "only available when logged in" in text or "subtitles are only available" in text:
        return ("该平台的字幕需要登录后才能获取（例如 B站）。请在项目根目录放置 cookies.txt "
                "后重试——可用浏览器扩展导出 Netscape 格式 Cookie，详见 README。")
    if "sign in to confirm you're not a bot" in text or "not a bot" in text:
        return ("该平台触发了人机校验，需要 Cookie 才能读取字幕。请在项目根目录放置 cookies.txt 后重试。")
    if "certificate_verify_failed" in text or "ssl" in text and "certificate" in text:
        return "访问该站点时出现证书/网络错误，请检查网络或代理后重试。"
    if "unable to download webpage" in text or "temporary failure in name resolution" in text \
            or "timed out" in text or "connection" in text and "refused" in text:
        return "无法访问该视频所在站点，请检查网络连接后重试。"
    if "private" in text or "login" in text or "authentication" in text:
        return "该视频需要登录才能访问字幕，请在项目根目录放置 cookies.txt 后重试。"
    return "该视频没有可用字幕，本工具当前仅支持有字幕的视频（后续版本将支持语音转写）"


def _find_subtitle(work_dir):
    """按 srt -> vtt 顺序返回字幕文件（--convert-subs 已统一为 srt）。"""
    for ext in (".srt", ".vtt"):
        for name in sorted(os.listdir(work_dir)):
            if name.lower().endswith(ext):
                path = os.path.join(work_dir, name)
                if os.path.getsize(path) > 0:
                    return path
    return None


def _clear_dir(path):
    for name in os.listdir(path):
        try:
            os.remove(os.path.join(path, name))
        except OSError:
            pass


def whisper_fallback(url):  # pragma: no cover - 二期预留
    """二期：无字幕时用 faster-whisper 下载音频并本地转写。

    预留接口，MVP 不实现；fetch_subtitle 失败时会给出明确提示。
    """
    raise NotImplementedError("本地语音转写将在二期提供")


# --------------------------------------------------------------------------
# 字幕解析（SRT / VTT 通用）→ 去噪后的时间轴序列
# --------------------------------------------------------------------------

_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
_STYLE_RE = re.compile(r"\{[^}]*\}")


def _parse_time(text):
    """解析 'HH:MM:SS,mmm' / 'MM:SS,mmm' / 'HH:MM:SS.mmm'，返回秒（float）。"""
    text = text.strip().replace(",", ".")
    parts = text.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        if len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        return float(parts[0])
    except (ValueError, IndexError):
        return None


def parse_subtitle(path):
    """解析字幕文件为 [{start, end, text}]，并做去重与短句合并。"""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    raw = raw.replace("\ufeff", "")

    cues = []
    lines = raw.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if "-->" not in line:
            index += 1
            continue
        left, _, right = line.partition("-->")
        # 去掉 VTT 的 cue settings（时间之后到行尾的参数）
        start = _parse_time(left.split()[-1] if left.split() else left)
        end = _parse_time(right.split()[0] if right.split() else right)
        index += 1

        text_lines = []
        while index < len(lines) and lines[index].strip():
            text_lines.append(lines[index].strip())
            index += 1
        while index < len(lines) and not lines[index].strip():
            index += 1

        if start is None or end is None:
            continue
        text = clean_cue_text(" ".join(text_lines))
        if text:
            cues.append({"start": start, "end": end if end > start else start + 1.0, "text": text})

    return normalize_cues(cues)


def clean_cue_text(text):
    """去掉 HTML 标签、样式标记与重复空白。"""
    text = _STYLE_RE.sub("", text)
    text = _TAG_RE.sub("", text)
    text = text.replace("\\N", " ").replace("\\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def _norm_key(text):
    return re.sub(r"[\s\W_]+", "", text or "")


def normalize_cues(cues, min_duration=0.5):
    """去重（自动字幕大量滚动重复）+ 把过短碎片并入下一句。

    短碎片并入**下一句**而非上一句：字幕的滚动特性决定了碎片通常是下一句的开头
    （如「今天」+「我们来讲…」），向前合并会得到不通顺的文本。
    """
    deduped = []
    for cue in cues:
        if deduped and _norm_key(cue["text"]) == _norm_key(deduped[-1]["text"]):
            deduped[-1]["end"] = cue["end"]         # 重复行：只延长时间
            continue
        deduped.append(dict(cue))

    result = []
    pending = None
    for cue in deduped:
        if pending is not None:
            cue = {**cue, "start": pending["start"], "text": pending["text"] + cue["text"]}
            pending = None
        if (cue["end"] - cue["start"]) < min_duration:
            pending = cue
            continue
        result.append(cue)

    if pending is not None:
        if result:                                   # 结尾的孤立碎片并入上一句
            result[-1]["text"] += pending["text"]
            result[-1]["end"] = pending["end"]
        else:
            result.append(pending)
    return result


def cues_to_transcript(cues):
    """把时间轴序列渲染成送模型的文本（每行带 [mm:ss] 前缀）。"""
    return "\n".join(f"[{fmt_ts(c['start'])}] {c['text']}" for c in cues)


def _srt_time(seconds):
    """秒 -> SRT 时间格式 HH:MM:SS,mmm（毫秒分隔符是逗号，与 WebVTT 的点号不同）。"""
    try:
        total = max(0.0, float(seconds))
    except (TypeError, ValueError):
        total = 0.0
    ms = int(round(total * 1000))
    h, rem = divmod(ms, 3600 * 1000)
    m, rem = divmod(rem, 60 * 1000)
    s, ms_rem = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms_rem:03d}"


def cues_to_srt(cues):
    """时间轴 -> 标准 SRT 字幕（可导入播放器）。"""
    blocks = []
    for idx, cue in enumerate(cues or [], 1):
        text = str(cue.get("text") or "").strip()
        if not text:
            continue
        blocks.append(
            f"{idx}\n"
            f"{_srt_time(cue.get('start', 0))} --> {_srt_time(cue.get('end', 0))}\n"
            f"{text}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def cues_to_txt(cues):
    """时间轴 -> 纯文本字幕（[mm:ss] 文本，便于速读）。"""
    lines = []
    for cue in cues or []:
        text = str(cue.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"[{fmt_ts(cue.get('start', 0))}] {text}")
    return "\n".join(lines) + ("\n" if lines else "")


# --------------------------------------------------------------------------
# 大模型客户端（OpenAI 兼容 /chat/completions，标准库实现）
# --------------------------------------------------------------------------

def _endpoint():
    base = (LLM_BASE_URL or "").rstrip("/")
    if not base:
        raise SummaryError("未配置 LLM_BASE_URL")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def _post(payload, timeout):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        _endpoint(),
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": "Bearer " + LLM_API_KEY,
        },
        method="POST",
    )
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise SummaryError(_llm_error_summary(exc.code, body))
    except urllib.error.URLError as exc:
        raise SummaryError(f"无法连接大模型服务（{exc.reason}），请检查网络与 LLM_BASE_URL")
    except TimeoutError:
        raise SummaryError("大模型请求超时，可尝试调大 LLM_TIMEOUT 或稍后重试")


def _llm_error_summary(code, body):
    """只回传状态码与简短摘要，绝不回显 API Key 或完整请求体。"""
    brief = ""
    try:
        parsed = json.loads(body)
        err = parsed.get("error") or {}
        brief = err.get("message") or err.get("code") or ""
    except (ValueError, AttributeError):
        brief = ""
    if not brief:
        brief = (body or "").strip().splitlines()[0][:120] if body.strip() else ""
    brief = brief[:160]
    return f"大模型返回 HTTP {code}" + (f"：{brief}" if brief else "")


# 网关偶发中断/限流对应的 HTTP 状态码，遇到这些也重试
_TRANSIENT_HTTP = ("HTTP 408", "HTTP 425", "HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504")


def _is_transient(exc):
    """判断是否属于「偶发、可重试」的调用失败。"""
    if isinstance(exc, (http.client.RemoteDisconnected, http.client.IncompleteRead,
                        ConnectionResetError, ConnectionAbortedError,
                        BrokenPipeError, socket.timeout, TimeoutError)):
        return True
    if isinstance(exc, SummaryError):
        return any(code in str(exc) for code in _TRANSIENT_HTTP)
    return False


def _as_summary_error(exc):
    """把底层异常翻译成可读中文提示（不回显堆栈与密钥）。"""
    if isinstance(exc, SummaryError):
        return exc
    if isinstance(exc, http.client.RemoteDisconnected):
        return SummaryError(
            "大模型网关中途断开连接（已自动重试仍失败）。输出较长时较易触发，"
            "可稍后重试，或调小 LLM_MAX_TOKENS"
        )
    if isinstance(exc, http.client.IncompleteRead):
        return SummaryError("大模型返回数据不完整（已自动重试仍失败），请稍后重试")
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return SummaryError("大模型请求超时，可调大 LLM_TIMEOUT 或稍后重试")
    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
        return SummaryError("与大模型服务的连接被中断（已自动重试仍失败），请稍后重试")
    if isinstance(exc, urllib.error.URLError):
        return SummaryError(f"无法连接大模型服务（{exc.reason}），请检查网络与 LLM_BASE_URL")
    return SummaryError(f"大模型调用失败（{type(exc).__name__}），请稍后重试")


def _chat_once(messages, json_mode, timeout, max_tokens):
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "stream": False,
        "max_tokens": max_tokens or LLM_MAX_TOKENS,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    attempts = max(1, LLM_RETRY_ATTEMPTS)
    raw = None
    for attempt in range(1, attempts + 1):
        try:
            with _llm_slots:
                with _post(payload, timeout or LLM_TIMEOUT) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
            break
        except Exception as exc:                      # noqa: BLE001
            if not _is_transient(exc) or attempt >= attempts:
                raise _as_summary_error(exc)
            time.sleep(LLM_RETRY_DELAY * attempt)     # 线性退避：2s / 4s …

    try:
        data = json.loads(raw)
        return (data["choices"][0]["message"]["content"] or "").strip()
    except (ValueError, KeyError, IndexError, TypeError):
        raise SummaryError("大模型返回内容无法解析，请稍后重试")


def chat(messages, json_mode=False, timeout=None, max_tokens=None):
    """非流式调用，返回模型文本。

    JSON 模式会自适应降级：中转站背后的部分上游模型不支持 response_format，
    此时返回 400；检测到后自动去掉该参数重试一次，改为靠提示词约束输出。
    """
    if not llm_configured():
        raise SummaryError("未配置 LLM_API_KEY，请参考 llm_config.example.bat 配置后重启服务")

    if not json_mode:
        return _chat_once(messages, False, timeout, max_tokens)

    try:
        return _chat_once(messages, True, timeout, max_tokens)
    except SummaryError as exc:
        if "HTTP 400" not in str(exc):
            raise
        return _chat_once(messages, False, timeout, max_tokens)


def list_models(timeout=60):
    """拉取平台可用模型列表（GET {base}/models）。

    网关文档明确：路径必须是 /v1/models，不要用 /v1beta/models。
    返回的 id 即为 LLM_MODEL 可填的值。
    """
    if not llm_configured():
        raise SummaryError("未配置 LLM_API_KEY，请参考 llm_config.example.bat 配置后重启服务")
    base = (LLM_BASE_URL or "").rstrip("/")
    if not base:
        raise SummaryError("未配置 LLM_BASE_URL")
    req = urllib.request.Request(
        base + "/models",
        headers={"Authorization": "Bearer " + LLM_API_KEY, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise SummaryError(_llm_error_summary(exc.code, body))
    except urllib.error.URLError as exc:
        raise SummaryError(f"无法连接大模型服务（{exc.reason}），请检查网络与 LLM_BASE_URL")
    except TimeoutError:
        raise SummaryError("拉取模型列表超时")

    try:
        data = json.loads(raw)
    except ValueError:
        raise SummaryError("模型列表返回内容无法解析")

    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise SummaryError("模型列表返回格式异常")

    result = []
    for item in items:
        if isinstance(item, dict) and item.get("id"):
            result.append(str(item["id"]))
        elif isinstance(item, str):
            result.append(item)
    return sorted(set(result))


def chat_stream(messages, timeout=None):
    """流式调用，逐段产出文本（SSE：`data: {json}`，以 `data: [DONE]` 结束）。"""
    if not llm_configured():
        raise SummaryError("未配置 LLM_API_KEY，请参考 llm_config.example.bat 配置后重启服务")
    payload = {"model": LLM_MODEL, "messages": messages, "stream": True}

    with _llm_slots:
        with _post(payload, timeout or LLM_TIMEOUT) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    delta = json.loads(chunk)["choices"][0]["delta"]
                except (ValueError, KeyError, IndexError, TypeError):
                    continue
                piece = delta.get("content")
                if piece:
                    yield piece


# --------------------------------------------------------------------------
# 提示词与总结
# --------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "你是一位专业的视频内容分析助手，擅长把长视频字幕提炼为结构化学习笔记。"
    "你必须严格依据字幕内容作答，不编造字幕中没有的信息。"
)

JSON_SCHEMA_HINT = (
    "{\n"
    '  "overview": "一句话总览，不超过 60 字",\n'
    '  "summary": "200-400 字段落式总结摘要，使用 Markdown 排版（关键概念用 **加粗**，可用 - 要点列表与 ### 小标题），讲清视频讲什么、怎么讲、结论是什么",\n'
    '  "chapters": [{"start": 0, "end": 320, "title": "章节标题", "points": ["要点1", "要点2"]}],\n'
    '  "keypoints": ["核心知识要点 1", "核心知识要点 2"],\n'
    '  "mindmap": "- 主题\\n  - 子主题\\n    - 叶子节点"\n'
    "}"
)

SUMMARY_RULES = (
    "输出要求：\n"
    "1. 只输出一个 JSON 对象，不要输出解释、不要使用 Markdown 代码块以外的任何文字；\n"
    "2. overview 是一句话（不超过 60 字）；summary 是 200-400 字的段落式摘要（可 2-4 段），"
    "使用 Markdown 排版：关键概念用 **加粗**，要点可用 - 列表，需要分段时用 ### 小标题；"
    "二者内容互补但不要重复措辞；\n"
    "3. chapters 按 start 递增排列，覆盖整段视频，最多 12 章，start/end 为整数秒；\n"
    "4. keypoints 为 3-10 条核心知识要点，每条不超过 60 字；\n"
    "5. mindmap 使用 Markdown 缩进列表（- 开头，2 空格缩进一层），体现视频的知识结构；\n"
    "6. 语言与字幕主体语言保持一致。"
)


def build_summary_messages(title, duration, transcript):
    head = f"视频标题：{title or '未知'}"
    if duration:
        head += f"\n视频时长：{fmt_ts(duration)}"
    user = (
        f"{head}\n\n"
        f"以下是该视频的字幕（每行格式为 [mm:ss] 文本）：\n{transcript}\n\n"
        f"请按以下 JSON 结构输出总结：\n{JSON_SCHEMA_HINT}\n\n{SUMMARY_RULES}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def build_map_messages(title, chunk_text):
    user = (
        f"视频标题：{title or '未知'}\n\n"
        f"以下是视频某一段的字幕（格式 [mm:ss] 文本）：\n{chunk_text}\n\n"
        "请提炼这一段的关键内容，输出纯文本要点列表，每行一条，格式严格为：\n"
        "[mm:ss] 要点内容\n"
        "不要输出任何其他说明。"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def build_reduce_messages(title, notes):
    user = (
        f"视频标题：{title or '未知'}\n\n"
        f"以下是按时间顺序整理的分段要点：\n{notes}\n\n"
        f"请把它们汇总为完整的视频总结，按以下 JSON 结构输出：\n{JSON_SCHEMA_HINT}\n\n{SUMMARY_RULES}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def chunk_cues(cues, max_chars, overlap_cues=8):
    """按字符数把时间轴切块，块间保留少量重叠以承接上下文。"""
    chunks = []
    current = []
    size = 0
    for cue in cues:
        cost = len(cue["text"]) + 12
        current.append(cue)
        size += cost
        if size >= max_chars:
            chunks.append(current)
            if len(current) == 1:          # 单条就超限：不重叠，防止死循环
                current, size = [], 0
            else:
                tail = current[-overlap_cues:]
                current = list(tail)
                size = sum(len(c["text"]) + 12 for c in current)
    if current:
        chunks.append(current)
    return chunks


def summarize(title, duration, transcript, cues=None, progress=None):
    """整篇优先；超长或拿到 cues 时退化为分块 map-reduce。"""
    def report(value, note=""):
        if progress:
            progress(value, note)

    partial_failures = 0
    if cues and len(transcript) > SUMMARY_CHUNK_CHARS:
        report(55, "分段理解中")
        pieces = chunk_cues(cues, SUMMARY_CHUNK_CHARS)
        notes = []
        with ThreadPoolExecutor(max_workers=max(1, SUMMARY_MAX_CONCURRENCY)) as pool:
            futures = [
                pool.submit(chat, build_map_messages(title, cues_to_transcript(piece)))
                for piece in pieces
            ]
            for idx, future in enumerate(futures, 1):
                try:
                    notes.append(future.result())
                except Exception:                     # 单块失败不拖垮整体，最后统一标注
                    partial_failures += 1
                report(55 + int(25 * idx / max(len(futures), 1)), f"分段理解中（{idx}/{len(futures)}）")
        if not notes:
            raise SummaryError("分段理解全部失败，请稍后重试（可能是网关繁忙）")
        report(85, "汇总大纲中")
        content = chat(build_reduce_messages(title, "\n".join(notes)), json_mode=True)
    else:
        report(70, "生成大纲中")
        content = chat(build_summary_messages(title, duration, transcript), json_mode=True)

    result = parse_llm_json(content)
    if result is None:
        # 结构化失败：收紧提示重试一次；仍失败则降级为纯文本，绝不白屏
        retry = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "上一次输出不是合法 JSON。请仅输出 JSON 本身，不要任何多余文字。\n"
                                        f"结构：{JSON_SCHEMA_HINT}"},
            {"role": "assistant", "content": content[:4000]},
            {"role": "user", "content": "请重新输出严格合法的 JSON。"},
        ]
        content = chat(retry, json_mode=True)
        result = parse_llm_json(content)
    if result is None:
        return {
            "overview": (content or "")[:200],
            "summary": "",
            "chapters": [],
            "keypoints": [],
            "mindmap": "",
            "degraded": True,
        }
    if partial_failures:
        result["partial"] = True                      # 前端据此提示「结果可能不完整」
    return result


def parse_llm_json(text):
    """从模型输出中提取 JSON：直接解析 -> 代码块 -> 首尾花括号。"""
    if not text:
        return None
    text = text.strip()
    for candidate in (text, _from_code_block(text), _from_braces(text)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            return normalize_result(data)
    return None


def _from_code_block(text):
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    return match.group(1).strip() if match else None


def _from_braces(text):
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else None


def _as_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def normalize_result(data):
    """把模型输出规整成前端渲染契约，缺字段补默认值。"""
    chapters = []
    raw_chapters = data.get("chapters")
    if isinstance(raw_chapters, list):
        for item in raw_chapters:
            if not isinstance(item, dict):
                continue
            points = item.get("points")
            chapters.append({
                "start": _as_int(item.get("start"), 0),
                "end": _as_int(item.get("end"), 0),
                "title": str(item.get("title") or "").strip() or "未命名章节",
                "points": [str(p).strip() for p in points if str(p).strip()]
                if isinstance(points, list) else [],
            })
        chapters.sort(key=lambda c: c["start"])

    keypoints = data.get("keypoints")
    keypoints = [str(k).strip() for k in keypoints if str(k).strip()] \
        if isinstance(keypoints, list) else []

    # 段落式总结摘要：模型漏输出时留空，由前端回退到 overview，绝不报错
    summary = str(data.get("summary") or "").strip()

    return {
        "overview": str(data.get("overview") or "").strip(),
        "summary": summary,
        "chapters": chapters,
        "keypoints": keypoints,
        "mindmap": str(data.get("mindmap") or "").strip(),
        "degraded": False,
    }


# --------------------------------------------------------------------------
# 追问对话
# --------------------------------------------------------------------------

def build_ask_context(result, transcript):
    """上下文 = 总结全文；字幕不超过阈值时再附完整字幕。"""
    parts = [to_markdown(result, None)]
    if transcript and len(transcript) <= ASK_CONTEXT_CHARS:
        parts.append("以下是视频完整字幕（格式 [mm:ss] 文本）：\n" + transcript)
    return "\n\n".join(p for p in parts if p)


def build_ask_messages(question, context, history=None):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n\n你将基于下面这篇视频总结/字幕回答用户追问。\n\n" + context},
    ]
    for turn in (history or [])[-8:]:
        role = turn.get("role")
        content = str(turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:2000]})
    messages.append({"role": "user", "content": str(question).strip()[:2000]})
    return messages


# --------------------------------------------------------------------------
# 导出：Markdown / DOCX
# --------------------------------------------------------------------------

def to_markdown(result, meta=None):
    meta = meta or {}
    lines = []
    title = meta.get("title") or "视频总结"
    lines.append(f"# {title}")
    sub = []
    if meta.get("uploader"):
        sub.append(f"作者：{meta['uploader']}")
    if meta.get("duration"):
        sub.append(f"时长：{fmt_ts(meta['duration'])}")
    if meta.get("webpage_url"):
        sub.append(f"链接：{meta['webpage_url']}")
    if sub:
        lines.append("")
        lines.append(" · ".join(sub))

    lines.append("")
    lines.append("## 一句话总览")
    lines.append("")
    lines.append(result.get("overview") or "（无）")

    summary = (result.get("summary") or "").strip()
    if summary:
        lines.append("")
        lines.append("## 总结摘要")
        lines.append("")
        lines.append(summary)

    chapters = result.get("chapters") or []
    if chapters:
        lines.append("")
        lines.append("## 章节大纲")
        for chapter in chapters:
            span = f"{fmt_ts(chapter.get('start', 0))} - {fmt_ts(chapter.get('end', 0))}"
            lines.append("")
            lines.append(f"### [{span}] {chapter.get('title', '')}")
            for point in chapter.get("points") or []:
                lines.append(f"- {point}")

    keypoints = result.get("keypoints") or []
    if keypoints:
        lines.append("")
        lines.append("## 核心要点")
        for idx, point in enumerate(keypoints, 1):
            lines.append(f"{idx}. {point}")

    if result.get("mindmap"):
        lines.append("")
        lines.append("## 思维导图")
        lines.append("")
        lines.append(result["mindmap"])

    return "\n".join(lines)


_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")


def summary_blocks(summary):
    """把 Markdown 段落摘要切成结构化块，供 DOCX 排版。

    返回 [{"type": "h2"|"h3"|"p"|"ul"|"ol", "text"/"items": ...}]，
    只处理摘要需要的语法（小标题 / 列表 / 段落），不追求完整 Markdown 覆盖。
    """
    blocks = []
    for raw in (summary or "").splitlines():
        line = raw.strip()
        if not line:
            continue

        heading = re.match(r"^(#{2,4})\s+(.+)$", line)
        if heading:
            blocks.append({
                "type": "h2" if len(heading.group(1)) == 2 else "h3",
                "text": heading.group(2).strip(),
            })
            continue

        quote = re.match(r"^>\s?(.*)$", line)
        if quote:
            blocks.append({"type": "quote", "text": quote.group(1).strip()})
            continue

        bullet = re.match(r"^[-*+]\s+(.+)$", line)
        if bullet:
            item = bullet.group(1).strip()
            if blocks and blocks[-1]["type"] == "ul":
                blocks[-1]["items"].append(item)
            else:
                blocks.append({"type": "ul", "items": [item]})
            continue

        ordered = re.match(r"^\d+[.)]\s+(.+)$", line)
        if ordered:
            item = ordered.group(1).strip()
            if blocks and blocks[-1]["type"] == "ol":
                blocks[-1]["items"].append(item)
            else:
                blocks.append({"type": "ol", "items": [item]})
            continue

        blocks.append({"type": "p", "text": line})
    return blocks


def add_md_paragraph(document, text, style=None):
    """写入一段文本，把 **加粗** 拆成粗体 run（DOCX 没有 Markdown 概念）。"""
    paragraph = document.add_paragraph(style=style) if style else document.add_paragraph()
    text = text or ""
    pos = 0
    for match in _MD_BOLD.finditer(text):
        if match.start() > pos:
            paragraph.add_run(text[pos:match.start()])
        paragraph.add_run(match.group(1)).bold = True
        pos = match.end()
    if pos < len(text):
        paragraph.add_run(text[pos:])
    return paragraph


def to_docx(result, meta=None, out_path=None):
    """Markdown -> DOCX（python-docx）。返回文件路径。"""
    try:
        from docx import Document
        from docx.shared import Inches
    except ImportError:
        raise SummaryError("缺少 python-docx，请先运行 run.bat 安装依赖")

    meta = meta or {}
    document = Document()
    document.add_heading(meta.get("title") or "视频总结", level=0)

    sub = []
    if meta.get("uploader"):
        sub.append(f"作者：{meta['uploader']}")
    if meta.get("duration"):
        sub.append(f"时长：{fmt_ts(meta['duration'])}")
    if meta.get("webpage_url"):
        sub.append(f"链接：{meta['webpage_url']}")
    if sub:
        document.add_paragraph(" · ".join(sub))

    document.add_heading("一句话总览", level=1)
    document.add_paragraph(result.get("overview") or "（无）")

    summary = (result.get("summary") or "").strip()
    if summary:
        document.add_heading("总结摘要", level=1)
        for block in summary_blocks(summary):
            if block["type"] == "h2":
                document.add_heading(block["text"], level=2)
            elif block["type"] == "h3":
                document.add_heading(block["text"], level=3)
            elif block["type"] == "quote":
                add_md_paragraph(document, block["text"], style="Quote")
            elif block["type"] == "ul":
                for item in block["items"]:
                    add_md_paragraph(document, item, style="List Bullet")
            elif block["type"] == "ol":
                for item in block["items"]:
                    add_md_paragraph(document, item, style="List Number")
            else:
                add_md_paragraph(document, block["text"])

    chapters = result.get("chapters") or []
    if chapters:
        document.add_heading("章节大纲", level=1)
        for chapter in chapters:
            span = f"{fmt_ts(chapter.get('start', 0))} - {fmt_ts(chapter.get('end', 0))}"
            document.add_heading(f"[{span}] {chapter.get('title', '')}", level=2)
            for point in chapter.get("points") or []:
                document.add_paragraph(point, style="List Bullet")

    keypoints = result.get("keypoints") or []
    if keypoints:
        document.add_heading("核心要点", level=1)
        for point in keypoints:
            document.add_paragraph(point, style="List Number")

    if result.get("mindmap"):
        document.add_heading("思维导图", level=1)
        for line in result["mindmap"].splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            bullet = stripped.lstrip("-").strip()
            if not bullet:
                continue
            # 默认模板没有 "List Bullet 1"，层级改用缩进表达，避免样式缺失报错
            indent = len(line) - len(line.lstrip(" "))
            level = min(indent // 2, 4)
            paragraph = document.add_paragraph(bullet, style="List Bullet")
            if level:
                paragraph.paragraph_format.left_indent = Inches(0.25 * level)

    if not out_path:
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"{safe_filename(meta.get('title') or '视频总结')}.docx",
        )
    document.save(out_path)
    return out_path


# --------------------------------------------------------------------------
# 流水线（供 app.py 的后台线程调用）
# --------------------------------------------------------------------------

def run_summary(job, url):
    """完整流程：抓字幕 -> 解析 -> 总结。直接改写 job 字典。"""
    def progress(value, note=""):
        job["percent"] = min(99, max(job.get("percent", 0), int(value)))
        if note:
            job["stage_text"] = note

    job["stage"] = "fetching"
    progress(10, "正在抓取字幕")
    sub_path, meta = fetch_subtitle(url)

    job["meta"] = meta
    job["stage"] = "parsing"
    progress(40, "正在解析时间轴")
    try:
        cues = parse_subtitle(sub_path)
    finally:
        shutil.rmtree(os.path.dirname(sub_path), ignore_errors=True)

    if not cues:
        raise SummaryError("字幕内容为空，无法总结")

    transcript = cues_to_transcript(cues)
    job["cues"] = cues
    job["transcript"] = transcript

    job["stage"] = "summarizing"
    progress(55, "正在生成总结")
    result = summarize(meta.get("title"), meta.get("duration"), transcript, cues=cues, progress=progress)

    job["result"] = result
    job["stage"] = "done"
    job["percent"] = 100
    job["stage_text"] = "总结完成"
    job["finished_at"] = time.time()
    return result
