"""二期增量纯函数自测：字幕 SRT/TXT 生成 + summary 字段归一。

运行：python tests/test_summary_extras.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from summarizer import (  # noqa: E402
    add_md_paragraph,
    cues_to_srt,
    cues_to_txt,
    fmt_ts,
    normalize_result,
    summary_blocks,
)

CUES = [
    {"start": 1.0, "end": 4.2, "text": "第一条字幕"},
    {"start": 4.2, "end": 3661.5, "text": "第二条字幕"},
]


def test_srt_format():
    out = cues_to_srt(CUES)
    assert out.startswith("1\n00:00:01,000 --> 00:00:04,200\n第一条字幕"), out
    # 毫秒分隔符必须是逗号；超过 1 小时要用 HH:MM:SS
    assert "2\n00:00:04,200 --> 01:01:01,500\n第二条字幕" in out, out
    assert out.endswith("\n")


def test_srt_skips_empty():
    out = cues_to_srt([{"start": 0, "end": 1, "text": "  "}])
    assert out == ""


def test_txt_format():
    # TXT 用每条的 start（SRT 才有 end 区间）
    out = cues_to_txt(CUES)
    assert out.splitlines()[0] == "[00:01] 第一条字幕", out
    assert out.splitlines()[1] == "[00:04] 第二条字幕", out


def test_fmt_ts_hour():
    assert fmt_ts(3661) == "01:01:01"
    assert fmt_ts(61) == "01:01"


def test_normalize_summary_present():
    result = normalize_result({
        "overview": "一句话",
        "summary": "段落摘要",
        "keypoints": ["要点"],
    })
    assert result["summary"] == "段落摘要"
    assert result["keypoints"] == ["要点"]


def test_normalize_summary_missing():
    # 模型漏输出 summary 时不能炸，留空由前端回退 overview
    result = normalize_result({"overview": "一句话"})
    assert result["summary"] == ""
    assert result["overview"] == "一句话"


MD_SUMMARY = (
    "### 背景\n"
    "这是一段普通说明。\n"
    "- 要点一\n"
    "- 要点二\n"
    "## 结论\n"
    "1. 第一步\n"
    "2. 第二步\n"
)


def test_summary_blocks_structure():
    blocks = summary_blocks(MD_SUMMARY)
    types = [b["type"] for b in blocks]
    assert types == ["h3", "p", "ul", "h2", "ol"], types

    ul = [b for b in blocks if b["type"] == "ul"][0]
    assert ul["items"] == ["要点一", "要点二"]

    ol = [b for b in blocks if b["type"] == "ol"][0]
    assert ol["items"] == ["第一步", "第二步"]

    para = [b for b in blocks if b["type"] == "p"][0]
    assert para["text"] == "这是一段普通说明。"


def test_summary_blocks_empty():
    assert summary_blocks("") == []
    assert summary_blocks("   \n\n  ") == []


def test_add_md_paragraph_bold_runs():
    try:
        from docx import Document
    except ImportError:
        return                                  # 环境无 python-docx 时跳过

    doc = Document()
    paragraph = add_md_paragraph(doc, "这是**重点**内容")
    runs = paragraph.runs
    assert len(runs) == 3, [r.text for r in runs]
    assert runs[1].text == "重点"
    assert runs[1].bold is True
    assert runs[0].text == "这是" and runs[2].text == "内容"


def test_transient_classification_and_messages():
    import http.client
    import socket

    from summarizer import SummaryError, _as_summary_error, _is_transient

    assert _is_transient(http.client.RemoteDisconnected("boom"))
    assert _is_transient(http.client.IncompleteRead(b"x"))
    assert _is_transient(ConnectionResetError("reset"))
    assert _is_transient(socket.timeout("t"))
    assert _is_transient(SummaryError("大模型返回 HTTP 503：busy"))
    assert not _is_transient(SummaryError("未配置 LLM_API_KEY"))
    assert not _is_transient(ValueError("x"))

    err = _as_summary_error(http.client.RemoteDisconnected("boom"))
    assert isinstance(err, SummaryError)
    assert "断开连接" in str(err)
    assert "RemoteDisconnected" not in str(err)      # 不给用户抛技术类名


def test_chat_once_retries_then_succeeds():
    import http.client
    import json as _json

    import summarizer

    calls = {"n": 0}
    real_post = summarizer._post
    real_delay = summarizer.LLM_RETRY_DELAY
    summarizer.LLM_RETRY_DELAY = 0                   # 测试不真正等待

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return _json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")

    def flaky(payload, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise http.client.RemoteDisconnected("boom")
        return FakeResponse()

    try:
        summarizer._post = flaky
        out = summarizer._chat_once([{"role": "user", "content": "hi"}], False, None, 16)
        assert out == "ok"
        assert calls["n"] == 3                      # 前两次失败，第三次成功
    finally:
        summarizer._post = real_post
        summarizer.LLM_RETRY_DELAY = real_delay


def test_chat_once_exhausts_retries():
    import http.client

    import summarizer

    calls = {"n": 0}
    real_post = summarizer._post
    real_delay = summarizer.LLM_RETRY_DELAY
    summarizer.LLM_RETRY_DELAY = 0

    def always_fail(payload, timeout):
        calls["n"] += 1
        raise http.client.RemoteDisconnected("boom")

    try:
        summarizer._post = always_fail
        try:
            summarizer._chat_once([{"role": "user", "content": "hi"}], False, None, 16)
            raise AssertionError("应当抛出 SummaryError")
        except summarizer.SummaryError as exc:
            assert "断开连接" in str(exc)
        assert calls["n"] == max(1, summarizer.LLM_RETRY_ATTEMPTS)
    finally:
        summarizer._post = real_post
        summarizer.LLM_RETRY_DELAY = real_delay


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print("PASS  " + name)
        except AssertionError as exc:
            failures += 1
            print("FAIL  " + name + " -> " + str(exc))
    print("\n" + ("全部通过" if not failures else str(failures) + " 个用例失败"))
    sys.exit(1 if failures else 0)
