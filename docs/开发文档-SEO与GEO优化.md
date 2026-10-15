# 《万能视频下载总结器》SEO + GEO 优化 · 开发文档

> 项目：HJ 视频下载 / HJ Video Downloader（基于 yt-dlp 的网页端视频下载与 AI 总结工具）
> 开发周期：2026-10-15
> 目标：① 让站点在全网搜索引擎获得自然流量；② 让 AI 对话优先引用本站内容
> 原则：**只扩展能力，不改动任何既有功能**

---

## 一、背景与目标

### 1.1 项目现状

项目是一个 Python 3.13 + Flask 的单文件应用（`app.py`），配 `summarizer.py` 做 AI 总结，前端为原生 HTML/CSS/JS。开发启动前站点只有三个页面：

| 页面 | 说明 |
|---|---|
| `/` | 首页：Hero 输入区、解析结果、下载队列、支持平台、会员区块 |
| `/summarize` | AI 总结页：流水线进度、四段式结果、追问、导出 |
| `/pricing` | 定价页：三档套餐、权益对比、FAQ |

**有利条件**：Flask 服务端渲染（SSR），内容直出在 HTML 源码里。这对百度、搜狗、360 以及大量不执行 JS 的 AI 爬虫而言是天然优势，比 SPA 起点高。

### 1.2 业务目标拆解

1. **SEO 目标**：让用户能在全网各搜索引擎优先看到内容
2. **GEO 目标**：让用户在豆包 / DeepSeek / Kimi / 元宝 / 文心 / ChatGPT / Perplexity 等 AI 对话中优先看到本站内容

两个目标的差异决定了两套不同的打法：SEO 争夺搜索结果页的排名，GEO 争夺 AI 回答里的引用位。AI 更愿意引用**定义清晰、结构化、可摘录**的内容。

---

## 二、需求分析与人工确认

按项目约定，凡存在歧义的决策点必须先人工确认。两轮开发各确认 4 项，共 8 项：

### 2.1 第一轮：SEO

| # | 决策点 | 确认结果 |
|---|---|---|
| 1 | 站点正式域名 | 尚未部署 → 用 `SEO_BASE_URL` 环境变量驱动，本地默认 `http://127.0.0.1:8899`，上线改一处即可 |
| 2 | 优化范围 | **全都要**：基建 + 平台长尾落地页 + 内容页 + sitemap 自动汇总 |
| 3 | OG 分享图素材 | 由开发用项目主色（#1777FF / #FFB020）生成 |
| 4 | 站长验证与统计 | 暂不接入，只产出「上线后提交清单」文档，人工操作 |

### 2.2 第二轮：GEO

| # | 决策点 | 确认结果 |
|---|---|---|
| 1 | AI 爬虫策略 | **全部放行**（含训练类爬虫），最大化 AI 曝光 |
| 2 | 是否做对比/评测类页面 | **做，但只做客观对比** —— 基于公开事实，不点名贬低任何产品 |
| 3 | 是否改动现有页面 | **允许追加，纯新增不动布局** —— 只加区块，不改已有结构与样式 |
| 4 | 语言范围 | **中英双语** + hreflang，覆盖国内与海外 AI 的英文提问 |

---

## 三、现状审计（改造前的基线问题）

| # | 问题 | 影响 |
|---|---|---|
| 1 | 无 `robots.txt`、无 `sitemap.xml` | 高：搜索引擎发现与收录链路完全缺失 |
| 2 | 无 `canonical` | 高：127.0.0.1 / 域名 / 带参 URL 会被判重复内容 |
| 3 | 无 Open Graph / Twitter Card | 高：社交分享无标题无图，且拿不到富摘要 |
| 4 | 无 JSON-LD 结构化数据 | 高：无法获得富文本摘要 |
| 5 | 无 `keywords` meta | 中：Google 已弃用，但百度/360/搜狗仍参考 |
| 6 | 无 OG 分享图（1200×630） | 中：OG 标签的硬性依赖 |
| 7 | 图片 `alt` 为空 | 中：`summarize.html` 封面图 `alt=""` |
| 8 | 无 404 页面 | 中：软 404 浪费抓取预算 |
| 9 | 首页「支持平台」仅名称罗列，无可读正文 | 高：唯一能吃长尾词的位置全是装饰性内容 |
| 10 | 无长尾落地页 / 内容页 | 高：主赛道「视频下载」是红海，长尾词才是机会 |
| 11 | 脚本未加 `defer` | 低—中：影响 LCP/INP |
| 12 | 未提交站长平台、无统计 | 中：上线后无法度量 |

### 核心策略判断

主赛道「视频下载」「视频下载器」属于超级红海，新站几乎不可能排上去。真正的机会在**长尾意图词**：`B站视频下载`、`YouTube视频下载 MP4`、`抖音视频保存到本地`、`小红书视频下载`、`AI视频总结`、`B站一键总结`。这需要**平台落地页**承载 —— 这也是本轮 SEO 投入的重点，而非单纯修标签。

---

## 四、方案设计

### 4.1 总体架构：数据 / 引擎 / 模板三层

```
数据层   data/seo/**.json         中文内容
        data/seo_en/**.json      英文内容（slug 与中文一一对应）
           ↓
引擎层   seo_content.py           读取 + 缓存 + 多语言合并
        seo.py                   TDK / canonical / hreflang / JSON-LD / sitemap
        seo_geo.py               robots（AI 爬虫）/ llms.txt / llms-full.txt
           ↓
模板层   templates/seo/head.html  统一 Meta 片段（所有页面 include）
        templates/seo/*.html     nav / footer / 答案块 / 下载组件
        templates/*.html         中文页面
        templates/en/*.html      英文页面（/en 前缀）
```

### 4.2 关键设计决策（含理由）

| 决策 | 理由 |
|---|---|
| **内容全部 JSON 化** | 改文案不用动 Python 代码；新增平台 = 复制一个 JSON 文件并重启，路由/sitemap/llms.txt 全自动生成 |
| **TDK 由 `seo.py` 单点生成** | 避免模板硬编码造成 TDK 重复；统一长度与格式规范 |
| **`SEO_BASE_URL` 环境变量驱动** | canonical、og:url、sitemap 全部绝对地址；上线只改一处，杜绝重复内容 |
| **平台落地页放在根路径** | `/bilibili-video-download` 比 `/download/bilibili` 更短且含关键词，利于 URL 权重 |
| **`/en` 前缀 + hreflang** | 子目录是 Google 推荐的多语言结构；`x-default` 指向中文版兜底 |
| **英文内容完整翻译** | 只翻译导航会被判为 thin content / duplicate，反而拖累全站质量信号 |
| **`llms.txt` + `llms-full.txt`** | llmstxt.org 新兴标准，零成本抢位；给 AI 一份「先看这里」的结构化索引 |
| **robots 显式放行 AI 爬虫** | 多数站点从未声明，容易被默认策略或中间件拦掉，等于在 AI 世界隐形 |
| **答案块（一句话答案 + 要点 + 事实表）** | AI 抽取偏好定义式首句与表格；这是 GEO 性价比最高的改动 |
| **对比页只做客观对比** | 规避法律与体验风险，同时覆盖 AI 最高频的「XX 和 YY 哪个好」提问形态 |
| **不伪造 AggregateRating** | 无真实评分数据时伪造会触发结构化数据惩罚 |

### 4.3 内容矩阵设计

| 类型 | 数量 | 说明 |
|---|---|---|
| 平台长尾落地页 | 8 | YouTube / 哔哩哔哩 / 抖音 / 小红书 / 微博 / 快手 / Twitter-X / Instagram |
| 使用指南 | 4 + 1 索引 | 下载流程 / 失败排查 / AI 总结 / 版权合规 |
| 对比与选型 | 4 + 1 索引 | 工具怎么选 / yt-dlp vs youtube-dl / 下载 vs 录屏 / 下载 vs 总结 |
| 常见问题 | 1 | 14 条问答，分 4 组 |
| 404 页 | 1 | 友好中文 404，自动 `noindex` |
| 语言 | ×2 | 中英双语 |
| **合计可索引 URL** | **44** | sitemap 自动汇总 |

---

## 五、实施过程

### 阶段一：SEO 基建（第一轮）

1. 新建 `seo.py`：全站 TDK / canonical / OG / Twitter Card / itemprop / JSON-LD / sitemap 的唯一数据源
2. 新建 `seo_content.py`：JSON 数据加载器（进程内缓存，容错）
3. 新建 `templates/seo/head.html`，把三个现有页面的 `<title>` + `<meta description>` 两行替换为 `{% include %}`，**其余结构一行未动**
4. 新建落地页 / FAQ / 指南 / 404 模板，复用现有 `style.css` 的类名（`container` / `section` / `hero` / `platform-card` / `faq` / `upsell` 等）
5. `app.py` 扩展：上下文处理器注入 `seo` 变量、`/robots.txt`、`/sitemap.xml`、内容页路由、404 处理器
6. 生成 OG 分享图：先做 `og-cover.svg` 源文件，再用 Windows .NET（`System.Drawing`）绘制带中文标题的 `og-cover.png`（1200×630）
7. `style.css` **仅追加** `seo-` 前缀的新样式，不修改任何既有规则
8. 产出 `docs/SEO上线提交清单.md`

### 阶段二：GEO（第二轮）

1. `seo_content.py` 升级为多语言加载器（向后兼容，中文路径不变）
2. 新建 `seo_geo.py`：AI 爬虫清单（32 个 UA）+ `llms.txt` / `llms-full.txt` 生成器
3. 新建 `data/seo/answers.json`：每页答案块（一句话答案 + 要点 + 事实表 + 补充 FAQ）
4. 新建对比内容数据 4 篇（中文）+ 4 篇（英文），含 `matrix` 对比表格与 `pick` 场景化结论
5. 结构化数据增强：`Organization.sameAs`、`WebPage.speakable`、`dateModified`、指南/对比用 `TechArticle`
6. 现有页面纯追加答案块（`seo/answer_block.html` + `seo/answer_faq.html`）
7. 英文内容 22 份 JSON + 英文模板 11 个 + `/en` 路由 + hreflang（HTML + sitemap 双通道）
8. 产出 `docs/GEO优化说明.md`

### 阶段三：验证

1. 冒烟测试：44 个路由状态码 + 标题唯一性 + 标签完整性 + JSON-LD 解析
2. 数据体检：44 个 JSON 合法性 + 字符纯度（韩文/西里尔/假名检测）
3. 实机启动服务，curl 验证全部端点
4. 既有功能回归：真实 B站链接调用 `/api/info` 验证下载链路未受影响

---

## 六、关键实现细节

### 6.1 页面元信息的生成链路

```python
# app.py：上下文处理器，所有模板自动获得 seo / ui / answer 等变量
@app.context_processor
def inject_seo_meta():
    path = request.path if has_request_context() else "/"
    meta = seo.meta_for(path)
    lang = meta["lang"]          # 由路径前缀自动判定 zh / en
    return {
        "seo": meta,             # title / description / canonical / alternate / jsonld ...
        "lang": lang,
        "ui": seo_content.load_ui(lang),
        "answer": meta.get("answer") or {},
        "footer_platforms": platform_links(lang),
    }
```

- `seo.meta_for(path)` 按路径查注册表，未注册的路径自动输出 `noindex, follow`（404 页因此天然不被索引）
- `alternate` 字段按 `/en` 前缀变换自动配对另一语言，找不到对应语言时不输出该条 hreflang

### 6.2 路由自动注册（数据驱动）

```python
def register_platform_pages():
    for lang in ("zh", "en"):
        platforms = dict(seo_content.load_platforms(lang))
        for slug, data in platforms.items():
            full_path = (EN + base_path) if lang == "en" else base_path
            app.add_url_rule(full_path, "platform_%s_%s" % (lang, slug), view)
```

新增平台落地页 = 放一个 JSON 文件 + 重启，无需改路由代码。

### 6.3 结构化数据分配

| 页面 | JSON-LD 类型 |
|---|---|
| 首页 | Organization（含 `sameAs`）+ WebSite + SoftwareApplication + WebPage（含 `speakable`） |
| `/summarize`、`/pricing` | WebPage + BreadcrumbList |
| `/faq` | WebPage + FAQPage + BreadcrumbList |
| `/guides` | WebPage + ItemList + BreadcrumbList |
| 指南详情 | TechArticle + BreadcrumbList |
| 对比详情 | TechArticle + FAQPage（场景化结论）+ BreadcrumbList |
| 平台落地页 | WebPage + FAQPage + BreadcrumbList |
| 404 | WebPage + BreadcrumbList，`robots` 输出 `noindex, follow` |

`_dump()` 在序列化时把 `</` 转义为 `<\/`，避免正文里的斜杠提前结束 `<script>` 标签。

### 6.4 llms.txt 生成

`seo_geo.llms_txt(lang)` 输出标准结构：

```
# 站点名
> 一句话描述
补充说明
## 产品事实清单
- 事实 1 … 
## 核心页面
- [标题](绝对 URL): 描述
## 分平台下载 / 使用指南 / 对比与选型
## Optional
- 全文版地址
- sitemap 地址
```

`llms-full.txt` 则把全站正文（平台 intro / caps / steps / FAQ、指南正文、对比表格）拼成 Markdown，**中文约 23k 字符，序列化后 56KB**。两份文件都随内容数据自动生成。

### 6.5 OG 分享图

- `static/img/og-cover.svg`：1200×630 源文件，含中文标题与三枚标签
- `static/img/og-cover.png`：1200×630 / 260KB，用 Windows 自带 .NET 的 `System.Drawing` 绘制（渐变背景 + 金色光晕 + 下载箭头图标 + 中文标题），**未引入任何第三方依赖**

---

## 七、测试与验证结果

### 7.1 冒烟测试（44 个路由）

| 检查项 | 结果 |
|---|---|
| 全部页面 HTTP 状态 | 44/44 返回 200 |
| Title 唯一性 | 无重复 |
| canonical / robots / keywords / OG / Twitter / itemprop | 全部存在 |
| JSON-LD 块 | 每页 2-4 块，`json.loads` 解析全部通过 |
| 404 路径（`/nope`、`/en/nope`、`/compare/nope`） | 全部 404 |
| `/api/*` 未匹配路径 | 保持 JSON 404（未被新 404 页拦截） |

### 7.2 GEO 专项检查

| 检查项 | 结果 |
|---|---|
| hreflang `zh-CN` / `en` / `x-default` | 全部输出且成对 |
| 英文页 `<html lang="en">` | OK |
| 答案块（中英） | 均渲染 |
| Organization `sameAs` / `speakable` / `dateModified` | 全部命中 |
| robots 关键 AI 爬虫（10 项抽样） | 全部命中 |
| sitemap | 44 条 URL + 132 个 `xhtml:link` |
| llms.txt / llms-full.txt（中英） | 均正常生成 |

### 7.3 数据体检

44 个 JSON 全部通过 `json.load` 校验，且未检出韩文、西里尔、日文假名、阿拉伯文、泰文等异常混入字符。

### 7.4 既有功能回归

```
POST /api/info  {"url": "https://www.bilibili.com/video/BV1GJ411x7h7"}
→ 200 {"title":"【官方 MV】Never Gonna Give You Up - Rick Astley",
        "duration":212.393, "formats":[1080p,720p,480p,360p], "uploader":"索尼音"}
POST /api/info  {}          → 400 {"error":"No URL provided"}
GET  /api/llm/config        → 200 {原样返回}
```

下载解析链路、Cookie 生效情况、接口错误契约均未变化。

---

## 八、上线与运营

### 8.1 部署必做

```
SEO_BASE_URL=https://你的域名     ← 唯一必须改的变量
HOST=0.0.0.0
PORT=8899
```

其余可选：`SEO_LASTMOD`（sitemap 的 lastmod）、`SEO_OG_IMAGE`（分享图路径）。

### 8.2 提交清单

详见 `docs/SEO上线提交清单.md`：

- 配置 `SEO_BASE_URL`、启用 HTTPS 并做 HTTP→HTTPS 301、统一 www 口径
- 提交 sitemap 到 Google Search Console / Bing / 百度搜索资源平台 / 360 / 搜狗 / 神马
- 百度优先用「API 主动推送」提交新页面（百度对 JS 渲染支持弱，本站 SSR 天然占优）
- 用 Google Rich Results Test 验证 SoftwareApplication / FAQPage / Article

### 8.3 GEO 上线动作

详见 `docs/GEO优化说明.md`：

- 确认 `/llms.txt` 与 `/llms-full.txt` 可公开访问，不能被登录墙拦住
- 直接到各 AI 平台提问验证（文档里列了 6 组推荐问题）
- 外部信号建设：GitHub 仓库 README、知乎/CSDN 真实经验分享

---

## 九、风险与后续

| 风险 / 待办 | 说明 |
|---|---|
| 域名未确定 | 上线前必须设置 `SEO_BASE_URL`，否则 canonical 仍是 127.0.0.1 |
| 内容深度可继续加厚 | 落地页正文字数直接影响长尾词排名，当前为可用水平，非最优 |
| 无真实评分数据 | 未添加 `AggregateRating`（伪造会触发惩罚），待有真实口碑后再补 |
| 图片 alt | 站内几乎无内容图片，后续新增图示时补 alt |
| 外部信号薄弱 | AI 更信任被多方提及的内容，站内已就绪，站外需持续投入 |
| 语音转写 | 无字幕视频的总结能力（Whisper 类）仍待实现，文档里已如实说明 |
| 未做多语言之外的语种 | 仅中英双语，后续可按同样结构扩展 |

---

## 十、附录

### 10.1 本次新增/修改文件清单

**新增（引擎）**
```
seo.py              SEO/GEO 元信息引擎：TDK、canonical、hreflang、JSON-LD、sitemap
seo_geo.py          robots（AI 爬虫放行）、llms.txt / llms-full.txt
seo_content.py      多语言内容加载器（data/seo、data/seo_en）
```

**新增（数据）**
```
data/seo/         中文：site_profile / faq / answers / ui
                  platforms(8) guides(4 + index) compare(4 + index)
data/seo_en/      英文：与中文一一对应，slug 保持一致
```

**新增（模板）**
```
templates/landing.html  faq.html  guides.html  guide.html
templates/compares.html compare.html  404.html
templates/seo/         head / nav / footer / answer_block / answer_faq / download_widget
templates/en/          英文版 11 个模板
```

**新增（静态资源）**
```
static/img/og-cover.svg   OG 图源文件
static/img/og-cover.png   1200×630 / 260KB 实际分享图
```

**修改（最小侵入）**
```
app.py                导入 seo / seo_geo / seo_content；新增上下文处理器与路由
templates/index.html      替换 head 两行 + 追加答案块；解析结果/下载队列上移到支持平台之前
templates/pricing.html    替换 head 两行 + 追加答案块（布局未变）
templates/summarize.html  替换 head 两行 + 追加答案块（置于结果区之后）
static/css/style.css      仅追加 seo- 前缀新样式
README.md                 目录结构 / 环境变量 / SEO / GEO 章节
```

**新增（文档）**
```
docs/SEO上线提交清单.md
docs/GEO优化说明.md
docs/开发文档-SEO与GEO优化.md   （本文档）
```

### 10.2 环境变量总表（新增部分）

| 变量 | 默认 | 说明 |
|---|---|---|
| `SEO_BASE_URL` | `http://127.0.0.1:8899` | 站点对外根地址，canonical/og:url/sitemap 均基于它 |
| `SEO_LASTMOD` | `2026-10-15` | sitemap 的 lastmod |
| `SEO_OG_IMAGE` | `/static/img/og-cover.png` | OG 分享图路径 |

> 原有变量（`PORT` / `MAX_CONCURRENT` / `COOKIE_FILE` / `LLM_*` 等）行为完全未变。

---

## 十一、修订记录

### R1 · 答案块遮挡了交互反馈（2026-10-15）

- **现象**：点击「开始总结」/「解析」后，进度与结果出现在很靠下的位置，用户必须滚过整个「要点速览」答案块才能看到
- **原因**：答案块被插入在输入框正下方，隔断了 `输入框 → 进度 → 结果` 这条反馈链路
- **处理**：把 `seo/answer_block.html` 移到结果区之后
  - `/summarize`：结果区之后
  - `/` 首页：下载队列之后
  - `/en` 英文首页：同步调整
- **结论**：GEO 答案块的位置以「不打断交互反馈」为前提。位置下移不影响 AI 抽取（AI 读取的是 HTML 全文，顺序不决定引用）

### R2 · 首页解析结果紧跟输入框（2026-10-15）

- **现象**：首页解析后，结果区中间隔着「支持平台」区块，用户需下滚才能看到
- **处理**：把「解析结果 + 下载队列」整体移到「支持平台」之前
- **最终顺序**：

  ```
  输入框 → 解析结果 → 下载队列 → 支持平台 → 答案块 → 会员区块 → FAQ
  ```

- **实测顺序**（DOM 偏移，越小越靠前）：

  | 区块 | 中文首页 | 英文首页 |
  |---|---|---|
  | 输入框 `urlInput` | 7293 | 8962 |
  | 解析结果 `cards` | 9053 | 10801 |
  | 下载队列 `queueSection` | 9653 | 11339 |
  | 支持平台 `platforms` | 10071 | 11832 |

### 过程中的一次失误与修复

移动区块时，第一次粘贴多带了一份「支持平台」区块的头部，导致首页出现**重复的 `id="platforms"` 与重复的 YouTube 卡片**（HTML 结构被破坏）。发现后立即删除重复片段，并补做了一次全站结构校验：

- 12 个主要页面：`div / section / article / aside / ul / ol / li / table / details` 开闭标签配对全部一致
- 所有页面 `id` 无重复、`H1` 数量均为 1
- 首页平台卡片数 12（与原始设计一致，未重复）

**教训**：大段 HTML 移动应采用「先删除、再插入」的分步方式，改后必须做结构校验，避免一次性整块替换带来的重复风险。
