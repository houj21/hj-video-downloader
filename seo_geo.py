# -*- coding: utf-8 -*-
"""GEO（生成式引擎优化）模块：面向 AI 对话与 AI 搜索引擎的输出。

负责三件事：
1. robots.txt —— 显式放行主流 AI 爬虫（默认策略下它们可能被中间件拦掉）
2. llms.txt —— llmstxt.org 标准：给大模型一份「先看这里」的结构化目录
3. llms-full.txt —— 纯全文版本，便于一次性被 AI 读取与引用

纯读取操作，不触碰下载 / 总结的任何业务逻辑。
"""

import seo
import seo_content

DEFAULT_LANG = seo.DEFAULT_LANG

# ---------------------------------------------------------------------------
# AI 爬虫清单（按用途分组，全部显式放行）
# ---------------------------------------------------------------------------

# 通用搜索与知识库索引型 AI
SEARCH_AI_AGENTS = [
    "GPTBot",                 # OpenAI：抓取用于模型训练与插件索引
    "OAI-SearchBot",          # OpenAI：ChatGPT 搜索索引
    "ChatGPT-User",           # OpenAI：用户提问时实时访问
    "ClaudeBot",              # Anthropic：抓取索引
    "Claude-User",            # Anthropic：用户提问时实时访问
    "Claude-SearchBot",       # Anthropic：搜索索引
    "anthropic-ai",           # Anthropic 旧标识
    "PerplexityBot",          # Perplexity 搜索引擎
    "Perplexity-User",        # Perplexity 用户触发访问
    "Google-Extended",        # Google：控制 Gemini / Vertex AI grounding
    "Applebot",               # Apple：Siri / Spotlight 索引
    "Applebot-Extended",      # Apple：AI 训练控制开关
    "YouBot",                 # You.com
    "DuckAssistBot",          # DuckDuckGo AI Answers
    "cohere-ai",              # Cohere
    "cohere-training-data-crawler",
    "AI2Bot",                 # Allen Institute for AI
    "Diffbot",                # Diffbot 知识图谱
    "ImagesiftBot",           # Hive AI 图像索引
    "Omgili",                 # Webz.io 数据聚合
    "Omgilibot",
    "Timpibot",               # Timpi
    "CCBot",                  # Common Crawl（众多大模型语料来源）
    "Amazonbot",              # Amazon（Alexa / Rufus）
    "meta-externalagent",     # Meta AI
    "FacebookBot",            # Meta 抓取
]

# 国内 AI 与搜索引擎
CN_AI_AGENTS = [
    "Bytespider",             # 字节跳动（豆包等）
    "Baiduspider",            # 百度
    "Baiduspider-render",
    "Sogou web spider",       # 搜狗
    "Sogou inst spider",
    "360Spider",              # 360
    "360GPTBot",              # 360 智脑
    "TencentSpider",          # 腾讯
    "YisouSpider",            # 神马搜索
    "HuaweiSymantecSpider",   # 华为
    "JikeSpider",             # 即刻
]

DISALLOW = "/api/"


def robots_txt():
    """生成 robots.txt：对所有 AI 爬虫显式 Allow，同时保护接口路径。"""
    lines = ["# ============================================================",
             "# HJ 视频下载 / HJ Video Downloader",
             "# 策略：欢迎所有搜索引擎与 AI 助手抓取本站内容（GEO 友好）",
             "# ============================================================",
             "",
             "User-agent: *",
             "Allow: /",
             "Disallow: %s" % DISALLOW,
             "",
             "# ---- 海外 AI 助手与 AI 搜索 ----"]
    lines.append("User-agent: " + "\nUser-agent: ".join(SEARCH_AI_AGENTS))
    lines += ["Allow: /", "Disallow: %s" % DISALLOW, "",
              "# ---- 国内 AI 助手与搜索引擎 ----"]
    lines.append("User-agent: " + "\nUser-agent: ".join(CN_AI_AGENTS))
    lines += ["Allow: /", "Disallow: %s" % DISALLOW, "",
              "Sitemap: %s" % seo.abs_url("/sitemap.xml"),
              ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# llms.txt / llms-full.txt
# ---------------------------------------------------------------------------


def _bullet(text):
    return "- " + (text or "").strip()


def _link(title, path, description=None):
    line = "- [%s](%s)" % (title.strip(), seo.abs_url(path))
    if description:
        line += ": " + description.strip().rstrip("。")
    return line


def llms_txt(lang=DEFAULT_LANG):
    """llmstxt.org 规范：一句话描述 + 分类 links + Optional 段。"""
    profile = seo_content.load_site_profile(lang)
    ui = seo_content.load_ui(lang)
    registry = seo._build_registry()

    name = ui.get("site_name") or profile.get("name")
    lines = ["# %s" % name, ""]

    desc = (profile.get("description") or "").strip()
    if desc:
        lines += ["> " + desc, ""]

    detail = (profile.get("detail") or "").strip()
    if detail:
        lines += [detail, ""]

    bullets = profile.get("bullets") or []
    if bullets:
        lines += ["## %s" % ui.get("llms_head_profile", "Product Facts"), ""]
        lines += [_bullet(b) for b in bullets]
        lines.append("")

    def section(title, paths_desc):
        exists = [(t, p, d) for t, p, d in paths_desc if registry.get(p)]
        if not exists:
            return []
        out = ["## %s" % title, ""]
        out += [_link(t, p, d) for t, p, d in exists]
        out.append("")
        return out

    home = seo.LANGS[lang]["prefix"] or "/"
    lines += section(ui.get("llms_head_core", "Core Pages"), [
        (ui.get("nav_home", "Home"), home, profile.get("tagline")),
        (ui.get("nav_summarize", "AI Summary"), seo.localized_path("/summarize", lang), None),
        (ui.get("nav_pricing", "Pricing"), seo.localized_path("/pricing", lang), None),
        (ui.get("nav_guides", "Guides"), seo.localized_path("/guides", lang), None),
        (ui.get("nav_compare", "Comparisons"), seo.localized_path("/compare", lang), None),
        (ui.get("nav_faq", "FAQ"), seo.localized_path("/faq", lang), None),
    ])

    lines += section(ui.get("llms_head_platforms", "Platform Downloads"), [
        (p.get("name"), p.get("path"), p.get("description"))
        for _, p in seo_content.load_platforms(lang)
    ])

    lines += section(ui.get("llms_head_guides", "Guides"), [
        (g.get("h1"), g.get("path"), g.get("description"))
        for _, g in seo_content.load_guides(lang)
    ])

    lines += section(ui.get("llms_head_compare", "Comparisons"), [
        (c.get("h1"), c.get("path"), c.get("description") or c.get("tldr"))
        for _, c in seo_content.load_compares(lang)
    ])

    lines += ["## %s" % ui.get("llms_head_optional", "Optional"), ""]
    lines.append(_bullet(ui.get("llms_full_note", "Full plain-text version") +
                         ": " + seo.abs_url(seo.localized_path("/llms-full.txt", lang))))
    lines.append(_bullet(ui.get("llms_sitemap_note", "Sitemap") +
                         ": " + seo.abs_url("/sitemap.xml")))
    lines.append("")
    return "\n".join(lines) + "\n"


def _paragraphs_to_text(items):
    return "\n\n".join(p.strip() for p in (items or []) if p)


def llms_full_txt(lang=DEFAULT_LANG):
    """全文版：把每个页面的正文按 Markdown 结构完整输出，供 AI 一次性读取。"""
    ui = seo_content.load_ui(lang)
    profile = seo_content.load_site_profile(lang)
    answers = seo_content.load_answers(lang)
    out = ["# %s" % (ui.get("site_name") or profile.get("name")), ""]

    desc = (profile.get("description") or "").strip()
    if desc:
        out += [desc, ""]

    # ---- 核心页 ----
    for page in seo.CORE_PAGES.get(lang, []):
        answer = answers.get(seo.strip_lang(page["path"], lang)) or {}
        out += ["## %s" % _title_head(page["title"], lang),
                "- URL: %s" % seo.abs_url(page["path"]), ""]
        if answer.get("tldr"):
            out += [answer["tldr"], ""]
        if answer.get("points"):
            out += [_bullet(p) for p in answer["points"]] + [""]
        if answer.get("facts"):
            out += _facts_lines(answer["facts"]) + [""]
        if answer.get("faq"):
            for item in answer["faq"]:
                out += ["### %s" % item.get("q", ""), item.get("a", ""), ""]

    # ---- FAQ ----
    faq = seo_content.load_faq(lang)
    if faq.get("groups"):
        out += ["## %s" % (faq.get("title") or "FAQ"),
                "- URL: %s" % seo.abs_url(faq.get("path")), ""]
        for group in faq["groups"]:
            out += ["### %s" % group.get("name", "")]
            for item in group.get("items", []):
                out += ["**%s**" % item.get("q", ""), item.get("a", ""), ""]

    # ---- 平台落地页 ----
    for _, p in seo_content.load_platforms(lang):
        out += ["## %s" % (p.get("h1") or p.get("name")),
                "- URL: %s" % seo.abs_url(p.get("path")), ""]
        answer = answers.get(p.get("path")) or {}
        if answer.get("tldr"):
            out += [answer["tldr"], ""]
        if p.get("intro"):
            out += [_paragraphs_to_text(p["intro"]), ""]
        if answer.get("facts"):
            out += _facts_lines(answer["facts"]) + [""]
        if p.get("caps"):
            out += [_bullet("%s：%s" % (c.get("name", ""), c.get("desc", ""))) for c in p["caps"]] + [""]
        if p.get("steps"):
            for i, step in enumerate(p["steps"], 1):
                out += ["%d. **%s**：%s" % (i, step.get("title", ""), step.get("text", ""))]
            out.append("")
        if p.get("notes"):
            out += [_bullet(n) for n in p["notes"]] + [""]
        if p.get("faq"):
            for item in p["faq"]:
                out += ["### %s" % item.get("q", ""), item.get("a", ""), ""]

    # ---- 使用指南 ----
    for _, g in seo_content.load_guides(lang):
        out += ["## %s" % (g.get("h1") or ""),
                "- URL: %s" % seo.abs_url(g.get("path")),
                "- %s: %s" % (seo.ui_text("article_published", lang, "Published"), g.get("date", "")), ""]
        if g.get("sub"):
            out += [g["sub"], ""]
        for sec in g.get("sections", []):
            out += ["### %s" % sec.get("heading", "")]
            out += [_paragraphs_to_text(sec.get("paragraphs")), ""]
        if g.get("conclusion"):
            out += [g["conclusion"], ""]

    # ---- 对比与选型 ----
    for _, c in seo_content.load_compares(lang):
        out += ["## %s" % (c.get("h1") or ""),
                "- URL: %s" % seo.abs_url(c.get("path")), ""]
        if c.get("tldr"):
            out += [c["tldr"], ""]
        matrix = c.get("matrix")
        if matrix:
            headers = matrix.get("headers") or []
            if headers:
                out += ["| " + " | ".join(headers) + " |",
                        "| " + " | ".join(["---"] * len(headers)) + " |"]
                for row in matrix.get("rows", []):
                    cells = [str(x) for x in row] + [""] * (len(headers) - len(row))
                    out.append("| " + " | ".join(cells[:len(headers)]) + " |")
                out.append("")
        for sec in c.get("sections", []):
            out += ["### %s" % sec.get("heading", "")]
            out += [_paragraphs_to_text(sec.get("paragraphs")), ""]
        if c.get("pick"):
            out += ["### %s" % c.get("pick_title", seo.ui_text("compare_pick_title", lang, "Quick Picks"))]
            for item in c["pick"]:
                out.append(_bullet("%s → %s" % (item.get("scenario", ""), item.get("answer", ""))))
            out.append("")
        if c.get("conclusion"):
            out += [c["conclusion"], ""]

    out += ["---", ui.get("llms_footer", "") or "",
            "%s: %s" % (seo.ui_text("nav_home", lang, "Home"), seo.abs_url(seo.LANGS[lang]["prefix"] or "/"))]
    return "\n".join(line for line in out if line is not None) + "\n"


def _facts_lines(facts):
    return [_bullet("%s：%s" % (f[0], f[1])) for f in facts if len(f) >= 2]


def _title_head(title, lang):
    head = (title or "").split("|")[0].strip()
    return head or (seo.SITE_NAME if lang == DEFAULT_LANG else seo.SITE_NAME_EN)
