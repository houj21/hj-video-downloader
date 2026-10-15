# -*- coding: utf-8 -*-
"""SEO / GEO 内容加载器：把 data/seo* 下的 JSON 数据读成 Python 结构。

设计要点：
- 内容以 JSON 存放，改文案不需要动 Python 代码
- 支持多语言：`zh` 读 data/seo，`en` 读 data/seo_en（互不干扰，向后兼容）
- 目录扫描 + 进程内缓存，不影响下载 / 总结的任何业务逻辑
- 任何文件缺失或格式错误都不会让站点崩溃，最多是该页面不出现在列表中
"""

import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 语言 -> 数据根目录
DATA_ROOTS = {
    "zh": os.path.join(BASE_DIR, "data", "seo"),
    "en": os.path.join(BASE_DIR, "data", "seo_en"),
}

# 语言 -> 通用三步引导
COMMON_STEPS = {
    "zh": [
        {
            "title": "复制链接",
            "text": "在浏览器地址栏复制完整视频网址，或从 App 分享菜单里选择「复制链接」。",
        },
        {
            "title": "粘贴解析",
            "text": "把链接粘进本页输入框（多个链接用空格分隔），点击「解析」，几秒内返回标题与清晰度列表。",
        },
        {
            "title": "选清晰度并下载",
            "text": "点选想要的清晰度或切换到 MP3 音频模式，点击下载，进度 100% 后再点「保存到本地」。",
        },
    ],
    "en": [
        {
            "title": "Copy the link",
            "text": "Copy the full video URL from the browser address bar, or tap Share → Copy Link in the app.",
        },
        {
            "title": "Paste and parse",
            "text": "Paste it into the box on this page (separate multiple links with spaces) and click Parse.",
        },
        {
            "title": "Pick quality and download",
            "text": "Choose a resolution, or switch to MP3 audio mode, then click Download and save to your device.",
        },
    ],
}

_cache = {}


def _cache_key(lang, kind):
    return "%s:%s" % (lang, kind)


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _scan(directory):
    """按文件名扫描目录下的 JSON，返回 [(slug, data)]；`_` 开头视为索引文件跳过。"""
    items = []
    if not os.path.isdir(directory):
        return items
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json") or name.startswith("_"):
            continue
        data = _read_json(os.path.join(directory, name))
        if not isinstance(data, dict):
            continue
        slug = data.get("slug") or name[:-5]
        data["slug"] = slug
        items.append((slug, data))
    items.sort(key=lambda kv: (int(kv[1].get("order") or 999), kv[0]))
    return items


def _root(lang):
    return DATA_ROOTS.get(lang, DATA_ROOTS["zh"])


def load_platforms(lang="zh"):
    """返回 [(slug, platform_data)]，落地页按 order 排序。"""
    key = _cache_key(lang, "platforms")
    if key not in _cache:
        result = []
        for slug, data in _scan(os.path.join(_root(lang), "platforms")):
            data.setdefault("steps", COMMON_STEPS.get(lang, COMMON_STEPS["zh"]))
            data.setdefault("caps", [])
            data.setdefault("notes", [])
            data.setdefault("faq", [])
            data.setdefault("intro", [])
            data.setdefault("domains", [])
            data.setdefault("related", [])
            result.append((slug, data))
        _cache[key] = result
    return _cache[key]


def load_guides(lang="zh"):
    """返回 [(slug, guide_data)]，指南文章按 order 排序。"""
    key = _cache_key(lang, "guides")
    if key not in _cache:
        result = []
        for slug, data in _scan(os.path.join(_root(lang), "guides")):
            data.setdefault("toc", [])
            data.setdefault("sections", [])
            result.append((slug, data))
        _cache[key] = result
    return _cache[key]


def load_compares(lang="zh"):
    """返回 [(slug, compare_data)]，对比/选型文章按 order 排序。"""
    key = _cache_key(lang, "compares")
    if key not in _cache:
        result = []
        for slug, data in _scan(os.path.join(_root(lang), "compare")):
            data.setdefault("toc", [])
            data.setdefault("sections", [])
            data.setdefault("matrix", [])
            result.append((slug, data))
        _cache[key] = result
    return _cache[key]


def load_guide_index(lang="zh"):
    index = _read_json(os.path.join(_root(lang), "guides", "_index.json")) or {}
    if lang == "en":
        index.setdefault("path", "/en/guides")
        index.setdefault("title", "Guides | HJ Video Downloader")
        index.setdefault("description", "HJ Video Downloader guides.")
    else:
        index.setdefault("path", "/guides")
        index.setdefault("title", "使用指南 | HJ 视频下载")
        index.setdefault("description", "HJ 视频下载使用指南合集。")
    index.setdefault("keywords", [])
    return index


def load_compare_index(lang="zh"):
    index = _read_json(os.path.join(_root(lang), "compare", "_index.json")) or {}
    if lang == "en":
        index.setdefault("path", "/en/compare")
        index.setdefault("title", "Comparisons & Buying Guides | HJ Video Downloader")
    else:
        index.setdefault("path", "/compare")
        index.setdefault("title", "工具对比与选型指南 | HJ 视频下载")
    index.setdefault("keywords", [])
    return index


def load_faq(lang="zh"):
    data = _read_json(os.path.join(_root(lang), "faq.json")) or {}
    if lang == "en":
        data.setdefault("path", "/en/faq")
    else:
        data.setdefault("path", "/faq")
    data.setdefault("groups", [])
    return data


def load_site_profile(lang="zh"):
    """站点档案：供 llms.txt 与 Organization sameAs 使用。"""
    key = _cache_key(lang, "site")
    if key not in _cache:
        data = _read_json(os.path.join(_root(lang), "site_profile.json")) or {}
        data.setdefault("name", "HJ 视频下载" if lang == "zh" else "HJ Video Downloader")
        data.setdefault("description", "")
        data.setdefault("sameAs", [])
        data.setdefault("bullets", [])
        data.setdefault("detail", "")
        _cache[key] = data
    return _cache[key]


def load_answers(lang="zh"):
    """返回 path -> 答案块配置（tldr / facts / points / faq）。"""
    key = _cache_key(lang, "answers")
    if key not in _cache:
        _cache[key] = _read_json(os.path.join(_root(lang), "answers.json")) or {}
    return _cache[key]


def load_ui(lang="zh"):
    """返回界面文案字典（模板里的通用措辞），缺 key 时回落到 zh。"""
    key = _cache_key(lang, "ui")
    if key not in _cache:
        data = _read_json(os.path.join(_root(lang), "ui.json")) or {}
        if lang != "zh":
            base = _read_json(os.path.join(DATA_ROOTS["zh"], "ui.json")) or {}
            merged = dict(base)
            merged.update({k: v for k, v in data.items() if v})
            data = merged
        _cache[key] = data
    return _cache[key]


def clear_cache():
    """仅供测试使用：清空进程内缓存以重新读取数据文件。"""
    _cache.clear()
