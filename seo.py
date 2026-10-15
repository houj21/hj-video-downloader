# -*- coding: utf-8 -*-
"""SEO / GEO 元信息引擎（只读，不参与下载 / 总结的任何业务逻辑）。

统一负责全站：
- TDK（Title / Description / Keywords）
- canonical、robots meta、hreflang（中英双语）
- Open Graph、Twitter Card、Schema.org itemprop
- JSON-LD（Organization / WebSite / SoftwareApplication / WebPage / FAQPage / Article / BreadcrumbList）
- 面向 AI 的答案块数据（answers.json）
- sitemap.xml

robots.txt 与 llms.txt / llms-full.txt 由「seo_geo.py」负责。

站点地址由环境变量 SEO_BASE_URL 驱动，上线只改这一个变量。

环境变量：
    SEO_BASE_URL   站点对外根地址
    SEO_LASTMOD    sitemap 的 lastmod
    SEO_OG_IMAGE   覆盖默认 OG 分享图
"""

import json
import os

import seo_content

BASE_URL = (os.environ.get("SEO_BASE_URL") or "http://127.0.0.1:8899").rstrip("/")
SITE_NAME = "HJ 视频下载"
SITE_ALT_NAME = "万能视频下载总结器"
SITE_TAGLINE = "粘贴链接，一键下载全网视频"
SITE_NAME_EN = "HJ Video Downloader"
OG_IMAGE = os.environ.get("SEO_OG_IMAGE") or "/static/img/og-cover.png"
SITE_LOGO = "/static/favicon.svg"
LOCALE = "zh_CN"
LANGUAGE = "zh-CN"
LAST_MOD = os.environ.get("SEO_LASTMOD") or "2026-10-15"

ROBOTS_DEFAULT = "index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1"
ROBOTS_NOINDEX = "noindex, follow"

# 语言配置：前缀 + hreflang 代码
LANGS = {
    "zh": {"prefix": "", "code": "zh-CN", "default": True},
    "en": {"prefix": "/en", "code": "en", "default": False},
}
DEFAULT_LANG = "zh"
EN_PREFIX = "/en"

# ---------------------------------------------------------------------------
# 核心页面（与现有 Flask 路由一一对应）
# ---------------------------------------------------------------------------
CORE_PAGES = {
    "zh": [
        {
            "key": "index",
            "path": "/",
            "title": "视频下载 - 粘贴链接一键保存全网视频 | HJ 视频下载",
            "description": (
                "粘贴链接即可下载 YouTube、B站、抖音等 1000+ 站点视频：支持 MP4 / MP3、"
                "清晰度自由选择、批量下载与播放列表自动展开，网页端直接操作，手机也能用。"
            ),
            "keywords": [
                "视频下载", "视频下载器", "在线视频下载", "MP4下载", "MP3下载",
                "批量视频下载", "视频解析", "万能视频下载", "HJ视频下载", "万能视频下载总结器",
            ],
            "priority": "1.0",
            "changefreq": "daily",
            "og_type": "website",
        },
        {
            "key": "summarize",
            "path": "/summarize",
            "title": "AI 视频总结 - 一分钟读懂一小时视频 | HJ 视频下载",
            "description": (
                "粘贴视频链接，AI 自动生成一句话总览、带时间戳的章节大纲、核心要点与思维导图，"
                "可基于字幕继续追问，并导出 Markdown / Word / PDF。只读字幕不下载视频，秒级出结果。"
            ),
            "keywords": [
                "AI视频总结", "视频总结", "视频转文字总结", "B站视频总结", "YouTube视频总结",
                "课程视频总结", "自动生成章节大纲", "视频笔记", "HJ视频下载",
            ],
            "priority": "0.9",
            "changefreq": "weekly",
            "og_type": "website",
        },
        {
            "key": "pricing",
            "path": "/pricing",
            "title": "定价方案 - 免费版与会员权益对比 | HJ 视频下载",
            "description": (
                "HJ 视频下载定价：免费版每天可下载 5 个视频，专业版解锁 4K 原画质、批量不限量与 AI 视频总结，"
                "另提供团队版。当前版本仅做权益展示，支付通道尚未接入。"
            ),
            "keywords": [
                "视频下载会员", "视频下载价格", "视频下载免费", "4K视频下载",
                "批量视频下载", "AI视频总结会员", "HJ会员权益",
            ],
            "priority": "0.8",
            "changefreq": "monthly",
            "og_type": "website",
        },
    ],
    "en": [
        {
            "key": "index",
            "path": EN_PREFIX,
            "title": "Video Downloader - Paste a Link, Save Any Video | HJ Video Downloader",
            "description": (
                "Paste a link to download videos from YouTube, Bilibili, Douyin and 1000+ sites. "
                "MP4/MP3 output, quality selection, batch downloads with zip packaging. Works in any browser, no install."
            ),
            "keywords": [
                "video downloader", "download online video", "save video to mp4", "mp3 converter",
                "batch video download", "youtube downloader", "bilibili downloader", "free video downloader",
            ],
            "priority": "0.9",
            "changefreq": "daily",
            "og_type": "website",
        },
        {
            "key": "summarize",
            "path": EN_PREFIX + "/summarize",
            "title": "AI Video Summarizer - Understand an Hour Video in a Minute | HJ Video Downloader",
            "description": (
                "Paste a video link and get an AI summary: one-line overview, timestamped chapters, key points and a mind map. "
                "Ask follow-up questions and export to Markdown, Word or PDF. Reads subtitles, not the whole video."
            ),
            "keywords": [
                "AI video summarizer", "video to text summary", "summarize youtube video",
                "video notes generator", "timestamped chapters", "AI summary tool",
            ],
            "priority": "0.8",
            "changefreq": "weekly",
            "og_type": "website",
        },
        {
            "key": "pricing",
            "path": EN_PREFIX + "/pricing",
            "title": "Pricing - Free Plan and Membership Benefits | HJ Video Downloader",
            "description": (
                "HJ Video Downloader pricing: the free plan allows 5 downloads per day, while the Pro plan unlocks 4K quality, "
                "unlimited batch downloads and AI summaries. Payments are not yet enabled; this page only shows planned benefits."
            ),
            "keywords": ["video downloader pricing", "free video downloader", "video downloader plans"],
            "priority": "0.7",
            "changefreq": "monthly",
            "og_type": "website",
        },
    ],
}

# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------


def abs_url(path):
    if not path:
        return BASE_URL + "/"
    return BASE_URL + (path if path.startswith("/") else "/" + path)


def _dump(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _escape_xml(text):
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(
        ">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")


def _normalize(path):
    path = (path or "/").strip()
    if not path.startswith("/"):
        path = "/" + path
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    return path


def detect_lang(path):
    path = _normalize(path)
    return "en" if path == EN_PREFIX or path.startswith(EN_PREFIX + "/") else DEFAULT_LANG


def strip_lang(path, lang=None):
    """去掉语言前缀，返回中立路径（用于配对另一语言）。"""
    lang = lang or detect_lang(path)
    prefix = LANGS[lang]["prefix"]
    if prefix and path.startswith(prefix):
        path = path[len(prefix):] or "/"
    return _normalize(path)


def localized_path(neutral_path, lang):
    """把中立路径转成指定语言的路径。"""
    neutral_path = _normalize(neutral_path)
    if lang == DEFAULT_LANG:
        return neutral_path
    return EN_PREFIX + ("" if neutral_path == "/" else neutral_path)


def localize_neutral_path(path, lang):
    """把带语言前缀的路径转换到目标语言的对应路径。"""
    return localized_path(strip_lang(path), lang)


# ---------------------------------------------------------------------------
# 结构化数据构造
# ---------------------------------------------------------------------------


def _breadcrumb(trail):
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name, "item": abs_url(path)}
            for i, (name, path) in enumerate(trail)
        ],
    }


def _speakable(selectors):
    return {"@type": "SpeakableSpecification", "cssSelector": selectors}


def _organization(lang):
    profile = seo_content.load_site_profile(lang)
    same_as = [u for u in profile.get("sameAs", []) if u]
    org = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": SITE_NAME if lang == DEFAULT_LANG else SITE_NAME_EN,
        "alternateName": SITE_ALT_NAME if lang == DEFAULT_LANG else SITE_NAME,
        "url": abs_url(LANGS[lang]["prefix"] + "/"),
        "logo": {"@type": "ImageObject", "url": abs_url(SITE_LOGO)},
        "description": profile.get("description") or SITE_TAGLINE,
    }
    if same_as:
        org["sameAs"] = same_as
    return org


def _webpage(meta, lang):
    return {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": meta["title"],
        "description": meta["description"],
        "url": meta["canonical"],
        "inLanguage": LANGS[lang]["code"],
        "primaryImageOfPage": {"@type": "ImageObject", "url": meta["og_image"]},
        "isPartOf": {"@type": "WebSite", "name": SITE_NAME, "url": BASE_URL + "/"},
        "about": {"@type": "Thing", "name": SITE_ALT_NAME},
        "dateModified": meta.get("date_modified") or LAST_MOD,
        "speakable": _speakable([".hero__title", ".hero__sub", ".seo-answer__tldr", ".seo-prose h2"]),
    }


def _home_schemas(meta, lang):
    organization = _organization(lang)
    prefix = LANGS[lang]["prefix"]
    website = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": SITE_NAME if lang == DEFAULT_LANG else SITE_NAME_EN,
        "alternateName": SITE_ALT_NAME if lang == DEFAULT_LANG else SITE_NAME,
        "url": abs_url(prefix + "/"),
        "inLanguage": LANGS[lang]["code"],
        "publisher": {"@type": "Organization", "name": SITE_NAME},
    }
    profile = seo_content.load_site_profile(lang)
    app = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": SITE_NAME if lang == DEFAULT_LANG else SITE_NAME_EN,
        "alternateName": SITE_ALT_NAME if lang == DEFAULT_LANG else SITE_NAME,
        "applicationCategory": "MultimediaApplication",
        "applicationSubCategory": "视频下载与 AI 总结" if lang == DEFAULT_LANG else "Video download and AI summarization",
        "operatingSystem": "Web（Windows / macOS / Android / iOS 浏览器）" if lang == DEFAULT_LANG else "Web (any modern browser)",
        "url": meta["canonical"],
        "description": meta["description"],
        "softwareVersion": "2.0",
        "featureList": profile.get("bullets") or [
            "1000+ 站点视频解析与下载" if lang == DEFAULT_LANG else "1000+ supported sites",
            "MP4 视频 / MP3 音频双模式" if lang == DEFAULT_LANG else "MP4 video / MP3 audio",
            "清晰度自由选择" if lang == DEFAULT_LANG else "Quality selection",
            "批量下载并自动打包 zip" if lang == DEFAULT_LANG else "Batch downloads with zip packaging",
            "AI 视频总结与基于字幕的追问" if lang == DEFAULT_LANG else "AI summaries and subtitle-based Q&A",
        ],
        "offers": {
            "@type": "Offer",
            "price": "0",
            "priceCurrency": "CNY",
            "availability": "https://schema.org/InStock",
            "description": "免费版每天可下载 5 个视频" if lang == DEFAULT_LANG else "Free plan: 5 downloads per day",
        },
    }
    return [organization, website, app]


def _faq_schema(items):
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in items
        ],
    }


def _article_schema(meta, headline, date_published, lang, kind="Article"):
    return {
        "@context": "https://schema.org",
        "@type": kind,
        "headline": headline,
        "description": meta["description"],
        "mainEntityOfPage": {"@type": "WebPage", "@id": meta["canonical"]},
        "url": meta["canonical"],
        "inLanguage": LANGS[lang]["code"],
        "datePublished": date_published,
        "dateModified": date_published,
        "author": {"@type": "Organization", "name": SITE_NAME, "url": BASE_URL + "/"},
        "publisher": {
            "@type": "Organization",
            "name": SITE_NAME,
            "logo": {"@type": "ImageObject", "url": abs_url(SITE_LOGO)},
        },
        "image": meta["og_image"],
        "speakable": _speakable([".hero__title", ".seo-answer__tldr", ".seo-prose h2"]),
    }


# ---------------------------------------------------------------------------
# 页面注册表
# ---------------------------------------------------------------------------
_REGISTRY = None


def _add_entry(entries, entry):
    if entry.get("path") and entry.get("title"):
        entries.append(entry)


def _build_registry():
    global _REGISTRY
    if _REGISTRY is not None:
        return _REGISTRY

    entries = []

    # ---- 核心页（中英各自一套 TDK） ----
    for lang, pages in CORE_PAGES.items():
        for page in pages:
            entry = dict(page)
            entry["lang"] = lang
            _add_entry(entries, entry)

    # ---- 数据驱动的页面（多语言目录） ----
    for lang in LANGS:
        # FAQ
        faq = seo_content.load_faq(lang)
        faq_items = [
            (item.get("q", ""), item.get("a", ""))
            for group in faq.get("groups", [])
            for item in group.get("items", [])
        ]
        _add_entry(entries, {
            "key": "faq",
            "lang": lang,
            "path": faq.get("path"),
            "title": faq.get("title"),
            "description": faq.get("description"),
            "keywords": faq.get("keywords") or [],
            "priority": "0.6",
            "changefreq": "monthly",
            "og_type": "website",
            "faq_items": faq_items,
        })

        # 使用指南索引
        guide_index = seo_content.load_guide_index(lang)
        _add_entry(entries, {
            "key": "guides",
            "lang": lang,
            "path": guide_index.get("path"),
            "title": guide_index.get("title"),
            "description": guide_index.get("description"),
            "keywords": guide_index.get("keywords") or [],
            "priority": "0.7",
            "changefreq": "weekly",
            "og_type": "website",
        })

        # 对比 / 选型索引
        compare_index = seo_content.load_compare_index(lang)
        _add_entry(entries, {
            "key": "compares",
            "lang": lang,
            "path": compare_index.get("path"),
            "title": compare_index.get("title"),
            "description": compare_index.get("description"),
            "keywords": compare_index.get("keywords") or [],
            "priority": "0.7",
            "changefreq": "monthly",
            "og_type": "website",
        })

        # 指南详情
        for slug, guide in seo_content.load_guides(lang):
            _add_entry(entries, {
                "key": "guide:%s" % slug,
                "lang": lang,
                "path": localized_path(guide.get("path") or "/guides/%s" % slug, lang),
                "title": guide.get("title"),
                "description": guide.get("description"),
                "keywords": guide.get("keywords") or [],
                "priority": "0.6",
                "changefreq": "monthly",
                "og_type": "article",
                "article": guide,
                "date_modified": guide.get("date"),
            })

        # 对比详情
        for slug, compare in seo_content.load_compares(lang):
            items = _extract_compare_faq(compare)
            _add_entry(entries, {
                "key": "compare:%s" % slug,
                "lang": lang,
                "path": localized_path(compare.get("path") or "/compare/%s" % slug, lang),
                "title": compare.get("title"),
                "description": compare.get("description") or compare.get("tldr"),
                "keywords": compare.get("keywords") or [],
                "priority": "0.7",
                "changefreq": "monthly",
                "og_type": "article",
                "article": compare,
                "compare": compare,
                "faq_items": items,
                "date_modified": compare.get("date"),
            })

        # 平台落地页
        for slug, platform in seo_content.load_platforms(lang):
            faq_items = [(item.get("q", ""), item.get("a", "")) for item in platform.get("faq", [])]
            _add_entry(entries, {
                "key": "platform:%s" % slug,
                "lang": lang,
                "path": localized_path(platform.get("path") or "/%s-video-download" % slug, lang),
                "title": platform.get("title"),
                "description": platform.get("description"),
                "keywords": platform.get("keywords") or [],
                "priority": "0.8",
                "changefreq": "weekly",
                "og_type": "website",
                "platform": platform,
                "faq_items": faq_items,
            })

    _REGISTRY = {entry["path"]: entry for entry in entries}
    return _REGISTRY


def _extract_compare_faq(compare):
    """对比页不单独写 FAQ 时的兜底：把结论段转成问答。"""
    items = []
    for pick in compare.get("pick", []):
        if pick.get("scenario") and pick.get("answer"):
            items.append((pick["scenario"], pick["answer"]))
    return items


def refresh():
    global _REGISTRY
    _REGISTRY = None
    seo_content.clear_cache()


def find(path):
    return _build_registry().get(_normalize(path))


def all_pages(lang=None):
    """返回 [(path, entry)]；lang 为空时返回全部语言。"""
    registry = _build_registry()
    ordered = []
    for page in CORE_PAGES.get("zh", []):
        entry = registry.get(page["path"])
        if entry:
            ordered.append((page["path"], entry))
    for path in sorted(registry):
        if any(path == p for p, _ in ordered):
            continue
        entry = registry[path]
        if lang and entry.get("lang") != lang:
            continue
        ordered.append((path, registry[path]))
    return ordered


# ---------------------------------------------------------------------------
# 模板消费的元信息
# ---------------------------------------------------------------------------


def _hreflang_alternates(path, entry_lang):
    registry = _build_registry()
    alternates = []
    for lang, conf in LANGS.items():
        candidate = localize_neutral_path(path, lang)
        if registry.get(candidate):
            alternates.append({"lang": conf["code"], "href": abs_url(candidate)})
    default = localize_neutral_path(path, DEFAULT_LANG)
    if len(alternates) > 1 and registry.get(default):
        alternates.append({"lang": "x-default", "href": abs_url(default)})
    return alternates


def meta_for(path, override=None):
    path = _normalize(path)
    entry = _build_registry().get(path)
    known = entry is not None
    lang = (entry or {}).get("lang") or detect_lang(path)
    entry = dict(entry) if entry else {}
    if override:
        entry.update({k: v for k, v in override.items() if v})

    robots = ROBOTS_DEFAULT if known else ROBOTS_NOINDEX
    canonical = abs_url(path)
    title = entry.get("title") or ("%s | %s" % (SITE_NAME, SITE_TAGLINE))
    description = entry.get("description") or ""
    keywords = entry.get("keywords") or []
    og_type = entry.get("og_type") or "website"
    og_image = abs_url(entry.get("og_image") or OG_IMAGE)
    og_title = entry.get("og_title") or title
    og_description = entry.get("og_description") or description
    alternate = _hreflang_alternates(path, lang)

    faq_items = [item for item in (entry.get("faq_items") or []) if item and item[0] and item[1]]
    article = entry.get("article")
    platform = entry.get("platform")
    compare = entry.get("compare")
    key = entry.get("key")
    is_home = path in (LANGS[lang]["prefix"] or "/", )

    # 答案块（GEO：给 AI 的可引用摘要）
    answers = seo_content.load_answers(lang)
    answer = answers.get(strip_lang(path, lang)) or {}

    if is_home:
        schemas = _home_schemas({"canonical": canonical, "description": description}, lang)
        # 首页同样输出 WebPage，带上 speakable / dateModified 以强化 AI 抽取信号
        schemas.append(_webpage({"title": title, "description": description,
                                 "canonical": canonical, "og_image": og_image,
                                 "date_modified": entry.get("date_modified")}, lang))
    elif article:
        schemas = [_article_schema(
            {"canonical": canonical, "description": description, "og_image": og_image},
            article.get("h1") or title,
            article.get("date") or LAST_MOD,
            lang,
            kind="TechArticle" if compare else "Article",
        )]
    else:
        schemas = [_webpage({"title": title, "description": description,
                             "canonical": canonical, "og_image": og_image,
                             "date_modified": entry.get("date_modified")}, lang)]

    if key == "guides":
        schemas.append({
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": guide_list_name(lang),
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i + 1,
                    "name": guide.get("h1"),
                    "url": abs_url(localized_path(guide.get("path"), lang)),
                    "description": guide.get("description"),
                }
                for i, (_, guide) in enumerate(seo_content.load_guides(lang))
            ],
        })

    if key == "compares":
        schemas.append({
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": compare_list_name(lang),
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i + 1,
                    "name": item.get("h1"),
                    "url": abs_url(localized_path(item.get("path"), lang)),
                    "description": item.get("description") or item.get("tldr"),
                }
                for i, (_, item) in enumerate(seo_content.load_compares(lang))
            ],
        })

    if faq_items:
        schemas.append(_faq_schema(faq_items))

    home_path = LANGS[lang]["prefix"] or "/"
    if known and path != home_path:
        if key == "guides":
            trail = [(SITE_NAME, home_path), (ui_text("nav_guides", lang), localized_path("/guides", lang))]
        elif key == "compares":
            trail = [(SITE_NAME, home_path), (ui_text("nav_compare", lang), localized_path("/compare", lang))]
        elif article and key.startswith("guide:"):
            trail = [
                (SITE_NAME, home_path),
                (ui_text("nav_guides", lang), localized_path("/guides", lang)),
                (article.get("h1") or title, path),
            ]
        elif compare:
            trail = [
                (SITE_NAME, home_path),
                (ui_text("nav_compare", lang), localized_path("/compare", lang)),
                (compare.get("h1") or title, path),
            ]
        elif platform:
            trail = [
                (SITE_NAME, home_path),
                (ui_text("nav_platforms", lang), home_path + "#platforms"),
                (platform.get("name"), path),
            ]
        else:
            trail = [(SITE_NAME, home_path), (title.split("|")[0].strip() or title, path)]
        schemas.append(_breadcrumb(trail))

    return {
        "title": title,
        "description": description,
        "keywords": ",".join(keywords),
        "robots": robots,
        "canonical": canonical,
        "alternate": alternate,
        "lang": lang,
        "og_type": og_type,
        "og_title": og_title,
        "og_description": og_description,
        "og_image": og_image,
        "og_image_alt": "%s - %s" % (SITE_NAME, SITE_TAGLINE),
        "og_url": canonical,
        "og_site_name": SITE_NAME,
        "og_locale": LOCALE if lang == DEFAULT_LANG else "en_US",
        "twitter_card": "summary_large_image",
        "twitter_site": "@hjvideodl",
        "itemprop_name": entry.get("itemprop_name") or title,
        "itemprop_description": entry.get("itemprop_description") or description,
        "itemprop_image": og_image,
        "jsonld": [_dump(schema) for schema in schemas],
        "answer": answer,
        "entry": entry,
        "known": known,
        "site_name": SITE_NAME,
        "site_alt_name": SITE_ALT_NAME,
        "base_url": BASE_URL,
        "date_modified": entry.get("date_modified") or LAST_MOD,
    }


def guide_list_name(lang):
    return "HJ 视频下载使用指南" if lang == DEFAULT_LANG else "HJ Video Downloader Guides"


def compare_list_name(lang):
    return "HJ 视频下载对比与选型" if lang == DEFAULT_LANG else "HJ Video Downloader Comparisons"


def ui(key):
    """模板调用：取当前语言的 UI 文案（由 app 的 context processor 注入）。"""
    table = seo_content.load_ui("zh")
    return table.get(key, key)


def ui_text(key, lang=DEFAULT_LANG, fallback=None):
    table = seo_content.load_ui(lang)
    return table.get(key, fallback or key)


# ---------------------------------------------------------------------------
# sitemap.xml
# ---------------------------------------------------------------------------


def sitemap_xml():
    urls = []
    for path, entry in all_pages():
        urls.append(
            "  <url>\n"
            "    <loc>%s</loc>\n"
            "    <lastmod>%s</lastmod>\n"
            "    <changefreq>%s</changefreq>\n"
            "    <priority>%s</priority>\n"
            "  </url>" % (
                _escape_xml(abs_url(path)),
                _escape_xml(entry.get("lastmod") or entry.get("date_modified") or LAST_MOD),
                _escape_xml(entry.get("changefreq") or "weekly"),
                _escape_xml(entry.get("priority") or "0.5"),
            )
        )
    # hreflang 扩展（Google 多语言站点地图）
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
        + "\n".join(_xml_url_with_alternates(path, entry) for path, entry in all_pages()) +
        "\n</urlset>\n"
    )


def _xml_url_with_alternates(path, entry):
    lines = ["  <url>", "    <loc>%s</loc>" % _escape_xml(abs_url(path))]
    for alt in _hreflang_alternates(path, entry.get("lang") or detect_lang(path)):
        lines.append(
            '    <xhtml:link rel="alternate" hreflang="%s" href="%s"/>'
            % (_escape_xml(alt["lang"]), _escape_xml(alt["href"]))
        )
    lines += [
        "    <lastmod>%s</lastmod>" % _escape_xml(entry.get("lastmod") or entry.get("date_modified") or LAST_MOD),
        "    <changefreq>%s</changefreq>" % _escape_xml(entry.get("changefreq") or "weekly"),
        "    <priority>%s</priority>" % _escape_xml(entry.get("priority") or "0.5"),
        "  </url>",
    ]
    return "\n".join(lines)
