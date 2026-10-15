# GEO 优化说明（生成式引擎优化）

目标：让豆包、DeepSeek、Kimi、元宝、文心一言，以及 ChatGPT、Perplexity、Gemini、Copilot 等 AI 对话在回答相关问题时，**优先引用本项目的内容**。

GEO 与普通 SEO 的区别在于：SEO 争夺的是搜索结果里的排名，GEO 争夺的是 AI 回答里那句「根据 HJ 视频下载的资料……」的引用位。AI 更愿意引用**定义清晰、结构化、可摘录**的内容。

---

## 一、本次完成的六件事

### 1. 显式放行全部 AI 爬虫（`/robots.txt`）

绝大多数站点其实从未声明过 AI 爬虫策略，一旦被默认策略、CDN 或反爬中间件拦掉，等于在 AI 世界里隐形。现在 `/robots.txt` 里逐条显式 `Allow`：

| 类别 | 覆盖的爬虫 |
|---|---|
| 海外 AI 助手 | GPTBot、OAI-SearchBot、ChatGPT-User、ClaudeBot、Claude-User、Claude-SearchBot、anthropic-ai、PerplexityBot、Perplexity-User、Google-Extended、Applebot、Applebot-Extended、YouBot、DuckAssistBot、cohere-ai、AI2Bot、Diffbot、Omgili、Timpibot、CCBot、Amazonbot、meta-externalagent、FacebookBot |
| 国内 AI 与搜索 | Bytespider（字节/豆包）、Baiduspider、360Spider、360GPTBot、Sogou、TencentSpider、YisouSpider（神马）、HuaweiSymantecSpider 等 |

`/api/` 仍然禁止抓取（接口不参与收录）。

### 2. `llms.txt` 与 `llms-full.txt`

遵循 llmstxt.org 的草案规范，相当于「给大模型的先看这里」：

- `/llms.txt`（约 6 KB）：一句话描述 + 产品事实清单 + 分类链接（核心页 / 分平台 / 指南 / 对比 / FAQ），末尾指向全文版与 sitemap
- `/llms-full.txt`（约 56 KB 纯文本）：全站正文的完整 Markdown，一次读取即可了解全站
- 英文对应 `/en/llms.txt`、`/en/llms-full.txt`

两份文件都由 `seo_geo.py` 从内容数据自动生成，**改 JSON 数据即同步更新，不用手工维护**。

### 3. 答案块：给 AI 准备可直接摘录的段落

每个页面顶部新增「要点速览」区块，固定三段结构：

1. **一句话答案**（`seo-answer__tldr`）：定义式首句，AI 最爱引用这一句
2. **核心要点**：3-6 条要点列表
3. **事实速查表**：`<名称, 事实>` 两列表格，AI 回答事实性问题时最易摘录

答案块内容放在 `data/seo/answers.json`（中文）与 `data/seo_en/answers.json`（英文），按 URL 作为 key。

> **位置策略（重要）**：答案块统一放在「解析结果 / 下载队列 / 流水线进度」**之后**，确保点击后的交互反馈紧跟输入框，不被遮挡。位置下移不影响 AI 抽取 —— AI 读取的是整份 HTML，顺序不决定是否引用。详见 `docs/开发文档-SEO与GEO优化.md` 的「修订记录 R1 / R2」。

### 4. 对比 / 选型类内容（AI 引用率最高的一类提问）

新增 4 篇客观对比，每篇都带 **对比表格 + 场景化结论**，且**不点名贬低任何具体产品**：

| 路径 | 回答的问题 |
|---|---|
| `/compare/best-video-downloader` | 视频下载工具怎么选（六维度 + 三形态 + 六场景） |
| `/compare/youtube-dl-vs-yt-dlp` | yt-dlp 和 youtube-dl 有什么区别 |
| `/compare/download-vs-screen-recording` | 下载和录屏有什么区别、什么情况不该下载 |
| `/compare/downloader-vs-ai-summary` | 先总结还是先下载 |

### 5. 结构化数据增强（让 AI 确认"你是谁"）

- `Organization.sameAs`：关联 GitHub 仓库与 yt-dlp，建立实体身份
- `WebPage.speakable`：标注首屏标题、副标题、答案块、正文小标题为可朗读/可播报区域
- `dateModified`：全站页面带上修改时间，AI 偏好时效性明确的内容
- 指南/对比页使用 `TechArticle`，带 `headline`、`datePublished`、`author`、`publisher`
- 对比页的场景化结论会以 FAQPage 形式一并输出

### 6. 中英双语 + hreflang

- 英文版统一使用 `/en` 前缀：`/en`、`/en/summarize`、`/en/pricing`、`/en/faq`、`/en/guides`、`/en/compare`、`/en/xxx-video-download`
- 每个页面输出 `hreflang="zh-CN"`、`hreflang="en"` 与 `hreflang="x-default"`
- sitemap 同时输出 `xhtml:link` 多语言标注（当前 44 条 URL / 132 个 hreflang 标签）
- **英文内容是完整翻译，不是只翻导航**（AI 与搜索引擎都能识别空壳翻译）

---

## 二、日常维护：新增一个平台落地页

1. 复制 `data/seo/platforms/bilibili.json` → 改名并改内容（中文）
2. 复制 `data/seo_en/platforms/bilibili.json` → 同样改（英文）
3. 两边 `slug`/`order` 保持一致，这样 hreflang 会自动配对
4. 在 `data/seo/answers.json` 与 `data/seo_en/answers.json` 里补一条要点速览
5. 重启服务，路由、`/sitemap.xml`、`/llms.txt` 同步生成

指南（`guides/`）与对比（`compare/`）同理。

---

## 三、如何验证 AI 有没有引用你

上线后可以直接在各 AI 里问下面这些问题，看是否出现本站内容：

- 「B站视频怎么下载到本地？」
- 「有没有不用装软件的视频下载工具？」
- 「yt-dlp 和 youtube-dl 有什么区别？」
- 「怎么快速看完一个一小时的视频？」
- 「下载视频和录屏哪个画质好？」
- 英文：`how to download bilibili video` / `yt-dlp vs youtube-dl`

如果还没出现，通常不是配置问题，而是**外部信号不足**：AI 更信任被多方提及的内容。建议同步做：

- GitHub 仓库 README 与 topic 写清楚（`houj21/hj-video-downloader`）
- 在知乎 / CSDN / 掘金 / V2EX 等平台做真实经验分享（不要灌水）
- 保持 `dateModified` 与内容更新节奏

---

## 四、上线后的补充动作

- [ ] 确认 `/llms.txt`、`/llms-full.txt` 可公开访问（不能被登录墙拦住）
- [ ] 把 `https://你的域名/llms.txt` 提交给支持该规范的 AI 搜索（如 Perplexity 的站点提交入口）
- [ ] 在各大 AI 平台直接提问验证，记录哪些问题已能引用
- [ ] 每月更新一次指南文章的时间戳（`date` 字段 + `SEO_LASTMOD`）

> 与 SEO 的协同：HTML 层的 TDK、canonical、sitemap 已由上一轮 SEO 完成，本轮 GEO 是在同一套内容数据上叠加的 AI 友好层，两者共用 `data/seo*` 与 `seo.py`，不存在重复维护。
