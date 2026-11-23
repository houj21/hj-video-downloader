# -*- coding: utf-8 -*-
"""本地视频总结功能回归测试（无 pytest，直接执行）。

用法：
    $env:MEMBERSHIP_DB="临时路径"; $env:SKIP_YTDLP_UPDATE="1"
    .venv\\Scripts\\python.exe tests\\test_local_summary.py
"""
import io
import os
import shutil
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

# 隔离数据库：测试一律使用临时库
_tmpdir = tempfile.mkdtemp(prefix="hjtest_local_")
os.environ.setdefault("MEMBERSHIP_DB", os.path.join(_tmpdir, "test.db"))
os.environ["SKIP_YTDLP_UPDATE"] = "1"

import app  # noqa: E402  导入时完成 init_db 与路由注册
import membership  # noqa: E402
import summarizer  # noqa: E402

PASS = 0
FAIL = []


def check(name, cond):
    global PASS
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}")


def raises(fn, exc=Exception):
    try:
        fn()
        return False
    except exc:
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 测试数据
SRT = """1
00:00:01,000 --> 00:00:04,000
今天我们来聊聊RAG

2
00:00:04,500 --> 00:00:09,000
首先看一下它的使用场景

3
00:00:09,500 --> 00:00:12,000
然后拆解技术全流程
"""

ASS = """[Script Info]
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize
Style: Default,微软雅黑,54

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,今天我们来聊聊RAG
Dialogue: 0,0:00:04.50,0:00:09.00,Default,,0,0,0,,字幕里的逗号, 不会破坏这一行
Dialogue: 0,0:00:09.50,0:00:12.00,Default,,0,0,0,,然后拆解{\\an8}技术全流程
"""


def make_files(tmp, video_name="课程.mp4", sub_name="课程.srt", sub_text=SRT):
    video = os.path.join(tmp, video_name)
    with open(video, "wb") as fh:
        fh.write(b"FAKE_MEDIA_BYTES")  # 非真实视频，ffprobe 解析失败属预期
    sub = os.path.join(tmp, sub_name)
    with open(sub, "w", encoding="utf-8") as fh:
        fh.write(sub_text)
    return video, sub


def register_and_login():
    """注册一个用户并直接写库开通终身会员，返回带会话的 test client。"""
    import time as _time
    email = "local-test@example.com"
    try:
        membership.create_user(email, "Passw0rd!123")
    except membership.MembershipError:
        pass                                    # 重复执行测试时用户已存在
    conn = membership.connect()
    row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    uid = row["id"]
    conn.execute(
        "INSERT OR IGNORE INTO memberships "
        "(user_id, plan, status, source_order_id, source_session_id, granted_at, expires_at) "
        "VALUES (?, 'lifetime', 'active', 'test', 'test', ?, NULL)",
        (uid, _time.time()),
    )
    conn.commit()
    conn.close()
    client = app.app.test_client()
    with client.session_transaction() as sess:
        sess["uid"] = uid
    return client


def job_row(job_id):
    return app.jobs.get(job_id)


def wait_job(job_id, timeout=5.0):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        row = job_row(job_id)
        if row and row.get("status") in ("done", "error"):
            return row
        time.sleep(0.05)
    return job_row(job_id)


def wait_uploads_cleared(timeout=3.0):
    """worker 的 finally（删除上传文件）可能晚于 status=done 被观察到，轮询等待清理。"""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not os.listdir(app.UPLOAD_DIR):
            return True
        time.sleep(0.05)
    return False


# ---------------------------------------------------------------- 1. 字幕解析
print("== 1. ASS/SSA 解析 ==")
_tmp = tempfile.mkdtemp(prefix="hjass_")
try:
    ass_path = os.path.join(_tmp, "sample.ass")
    with open(ass_path, "w", encoding="utf-8") as fh:
        fh.write(ASS)
    cues = summarizer.parse_subtitle(ass_path)
    check("ASS 解析出 3 条 cue", len(cues) == 3)
    check("ASS 时间解析正确", abs(cues[0]["start"] - 1.0) < 0.01 and abs(cues[0]["end"] - 4.0) < 0.01)
    check("ASS 文本中的逗号不破坏解析", any("不会破坏" in c["text"] for c in cues))
    check("ASS 样式标签被清理", all("an8" not in c["text"] for c in cues))

    srt_path = os.path.join(_tmp, "sample.srt")
    with open(srt_path, "w", encoding="utf-8") as fh:
        fh.write(SRT)
    check("SRT 解析不受影响", len(summarizer.parse_subtitle(srt_path)) == 3)
finally:
    shutil.rmtree(_tmp, ignore_errors=True)


# ---------------------------------------------------------------- 2. run_summary_from_file 管线
print("== 2. 本地文件总结管线 ==")
fake_result = {"tldr": "ok", "chapters": [], "keypoints": [], "mindmap": "", "memory": ""}
_orig_summarize = summarizer.summarize
summarizer.summarize = lambda *a, **k: fake_result
try:
    _tmp = tempfile.mkdtemp(prefix="hjpipe_")
    try:
        video, sub = make_files(_tmp)
        job = {"status": "running", "stage": "fetching", "percent": 0}
        summarizer.run_summary_from_file(job, video, sub)
        check("任务完成", job["status"] == "running" and job["stage"] == "done")
        check("标题取自文件名", job["meta"]["title"] == "课程")
        check("时长由 ffprobe 或字幕尾推算", bool(job["meta"].get("duration")))
        check("cues 已写入 job", len(job.get("cues") or []) == 3)
        check("local 标记存在", job["meta"].get("local") is True)

        job2 = {"status": "running", "stage": "fetching", "percent": 0}
        err = raises(lambda: summarizer.run_summary_from_file(job2, video, None),
                     summarizer.SummaryError)
        check("无外挂字幕且媒体无效时明确报错", err)
    finally:
        shutil.rmtree(_tmp, ignore_errors=True)
finally:
    summarizer.summarize = _orig_summarize


# ---------------------------------------------------------------- 3. 上传接口
print("== 3. 上传接口 /api/summarize/upload ==")
client = register_and_login()

# 3.1 未登录 401
anon = app.app.test_client()
resp = anon.post("/api/summarize/upload", data={})
check("未登录上传返回 401", resp.status_code == 401)

# 3.2 未提供文件 400
resp = client.post("/api/summarize/upload", data={})
check("缺少文件返回 400", resp.status_code == 400)

# 3.3 非法扩展名 400
resp = client.post("/api/summarize/upload", data={
    "video": (io.BytesIO(b"x"), "病毒.exe"),
}, content_type="multipart/form-data")
check("非法扩展名返回 400", resp.status_code == 400)

# 3.4 非法字幕扩展名 400
resp = client.post("/api/summarize/upload", data={
    "video": (io.BytesIO(b"x"), "v.mp4"),
    "subtitle": (io.BytesIO(b"x"), "s.lrc"),
}, content_type="multipart/form-data")
check("非法字幕格式返回 400", resp.status_code == 400)

# 3.5 正常上传（外挂字幕）→ 任务完成 → 文件被清理
_orig_summarize = summarizer.summarize
summarizer.summarize = lambda *a, **k: fake_result
try:
    resp = client.post("/api/summarize/upload", data={
        "video": (io.BytesIO(b"FAKE_MEDIA"), "机器学习入门.mp4"),
        "subtitle": (io.BytesIO(SRT.encode("utf-8")), "机器学习入门.srt"),
    }, content_type="multipart/form-data")
    check("正常上传返回 200", resp.status_code == 200)
    job_id = (resp.get_json() or {}).get("job_id")
    check("返回 job_id", bool(job_id))
    row = wait_job(job_id)
    check("任务完成且结果就绪", row and row.get("status") == "done")
    check("meta 标题来自上传文件名", (row.get("meta") or {}).get("title") == "机器学习入门")
    check("上传文件已被清理", wait_uploads_cleared())

    # 3.6 无字幕文件 + 无内封字幕流 → 400 任务错误信息可读
    resp = client.post("/api/summarize/upload", data={
        "video": (io.BytesIO(b"FAKE_MEDIA"), "novideo.mp4"),
    }, content_type="multipart/form-data")
    check("无字幕上传仍返回 200（错误走任务态）", resp.status_code == 200)
    row = wait_job((resp.get_json() or {}).get("job_id"))
    check("错误信息提示需要字幕", "字幕" in (row.get("error") or ""))
    check("失败后上传文件同样被清理", wait_uploads_cleared())

    # 3.7 大小限额（把上限临时调到 1KB）
    old_limit = app.UPLOAD_MAX_BYTES
    app.UPLOAD_MAX_BYTES = 1024
    try:
        resp = client.post("/api/summarize/upload", data={
            "video": (io.BytesIO(b"z" * 2048), "big.mp4"),
        }, content_type="multipart/form-data")
        check("超限返回 413", resp.status_code == 413)
        check("超限文件不残留", len(os.listdir(app.UPLOAD_DIR)) == 0)
    finally:
        app.UPLOAD_MAX_BYTES = old_limit
finally:
    summarizer.summarize = _orig_summarize


# ---------------------------------------------------------------- 4. 页面
print("== 4. 页面冒烟 ==")
html = client.get("/summarize").get_data(as_text=True)
check("总结页含来源切换", "tabOnline" in html and "tabLocal" in html)
check("总结页含上传面板", "uploadZone" in html and "videoFile" in html)
check("上传面板含字幕可选说明", "内封字幕" in html)


# ---------------------------------------------------------------- 结果
print()
if FAIL:
    print(f"== 结果：{PASS} 通过 / {len(FAIL)} 失败 ==")
    for name in FAIL:
        print("  失败项:", name)
    sys.exit(1)
print(f"== 结果：{PASS} 通过 / 0 失败 ==")

shutil.rmtree(_tmpdir, ignore_errors=True)
