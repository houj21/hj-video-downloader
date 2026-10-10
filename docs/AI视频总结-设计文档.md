# AI 视频总结 · 设计文档（竞品调研 + 方案设计）

| 项 | 内容 |
|---|---|
| 项目 | HJ 视频下载（`d:/ai/hj-video-downloader`）二期：AI 视频总结模块 |
| 文档版本 | v1.1（已实现版） |
| 创建日期 | 2026-10-09 |
| 更新日期 | 2026-10-10（思维导图重构为 ProcessOn 风格 + 默认接入公益大模型网关） |
| 状态 | 已实现并上线（本地提交 71bde4b，已推送 origin/main） |
| 溯源用途 | 本文件为后续开发的**唯一溯源主文档**；若与 `.codebuddy/plans/` 中的计划正文冲突，**以本文为准** |

---

## 一、需求背景与目标

用户在长视频学习场景中的痛点：想快速知道「一个 1 小时视频讲了什么」，不想逐帧看完。目标是用 AI 把视频转成可速读的结构化知识：

- 快速了解**视频大纲**（分章节、带时间戳，可回跳原视频）
- 抓住**核心知识要点**
- 必要时**基于内容继续追问**
- 结果**可导出留存**（Markdown / Word / PDF）

与既有下载能力形成闭环：**先看总结 → 判断是否值得精看或下载 → 再下载**。

---

## 二、竞品调研（2026-10 实地抓取）

### 2.1 BibiGPT（https://bibigpt.co/）

- **定位**：AI 音视频总结单点深耕。2023 年由吕立青（JimmyLv，前 ThoughtWorks / 阿里）创立，前身开源项目 BiliGPT，累计 100 万+ 用户。
- **核心能力**：1 小时视频 → 3 分钟阅读；**带时间戳的章节摘要**；全文转写；**思维导图**；AI 追问对话；图文改写（小红书 / 公众号 / 推特 / PPT）；Notion / Obsidian / flomo 一键保存；Pro 独占画面理解（视觉分析）。
- **平台**：YouTube、B站、抖音、快手、小红书、X、Vimeo、TED、Coursera、可汗学院、Apple Podcasts、Spotify、小宇宙、喜马拉雅 + 任意含 audio/video 标签网页；本地文件 mp3/mp4/m4a/wav/srt/vtt/ass。号称 30+ 来源。
- **客户端**：Web（bibigpt.co 中文 / aitodo.co 国际）+ Chrome/Firefox/Edge 插件 + Tauri 桌面端 + Expo 移动端 + MCP / OpenAPI / NLWeb / Anthropic Skill 四种 Agent 接入。
- **定价**：Free（每日额度，单视频 ≤30 分钟）／ Plus \$19.8 月（年 \$142.56，≤2h）／ Pro \$34.8 月（年 \$250.56，≤6h，含视觉分析 + 批量 + API）／ 终身 \$888 ／ credits \$20(2k) ~ \$200(40k)。国内支付宝/微信，约 \$×7.2 折算。
- **差异化打法**：**Agent First**。提供 `/api/mcp`（OAuth2+Bearer）、`openapi.json`、`/api/ask`（SSE）、`/.well-known/agent-card.json`、`/llms.txt`、`/pricing.md` —— 抢占「被 AI Agent 调用」的分发入口。

### 2.2 NoteGPT（https://notegpt.io/cn/bilibili-summarizer）

- **定位**：All-in-One AI 学习与工作智能体（大而全）。8000 万+ 全球用户、12000+ 学校与团队。B站总结器只是其 20+ 功能入口之一。
- **B站总结器主打**：10 秒出结构化摘要、**带时间戳**、**思维导图**、**双语转写**（中文全文 + 可选英文翻译）、导出 TXT / Markdown / PDF / Word、保存到「我的笔记」工作区。三步流程：输入链接 → 接收摘要 → 保存工作区。
- **其 SEO 打法**：一个平台一个独立落地页（`/cn/bilibili-summarizer`），主打「专为 B站打造，原生理解中文视频字幕，保留上下文」。
- **产品全景**：AI Agent、笔记、转录、TTS、播客、图像、视频解说、PPT、写作、闪卡、测验、PDF 翻译/总结、AI 检测器/去 AI 味、深度研究、数据分析图表。底层智能调度 GPT / Claude / Gemini / DeepSeek。
- **定价（双积分制：基础积分 + 高级积分）**：Pro \$9.99/月（年 \$108）／ Unlimited \$29/月（年 \$239）／ Max \$99/月（年 \$829）／ 团队 ≥3 人叠加 30%~50% 折扣 + 6 个月免费。免费版可用核心功能（总结/思维导图/翻译），无需信用卡。退款仅限首购 24 小时内。

### 2.3 横向对比

| 维度 | BibiGPT | NoteGPT | 我们 |
|---|---|---|---|
| 定位 | 单点深耕音视频总结 | 全能学习 Agent | **单点：下载 + 总结闭环** |
| 入口 | 链接 / 本地文件 / 插件 / 桌面 / 移动 | 链接 / 文件 / 浏览器插件 | 已有 yt-dlp 解析与下载，天然可支持本地文件 |
| 输出形态 | 时间戳摘要 + 转写 + 导图 + 图文改写 | 摘要 + 导图 + 双语转写 + PDF/Word | MVP 取交集：**总览 + 时间戳大纲 + 要点 + 导图** |
| 免费额度 | 每日额度、≤30 分钟 | 核心功能免费无卡 | 本地部署 = **无额度限制**，成本仅 token 费 |
| 商业模式 | 订阅 \$19.8~34.8 | 订阅 \$9.99~99 | 学习/自用项目，**不接付费墙** |
| 数据隐私 | 上传文件 30 天删除 | ISO27001 / SOC2 / GDPR | **本地闭环，字幕不出本机**（最大卖点） |

### 2.4 我们的独特机会（竞品做不到）

1. **本地闭环**：字幕/视频不出本机，无隐私风险，无平台风控。
2. **零边际成本**：无付费墙，1 小时视频字幕约 1-2 万汉字，DeepSeek 量级单次成本约几分钱。
3. **下载 + 总结一体**：竞品只总结不下载；我们形成「先看总结 → 决定是否下载」的决策闭环。
4. **多平台通吃**：复用现有 yt-dlp 1000+ 站点，比 NoteGPT「一平台一页」更通用。

---

## 三、方案决策记录

### 3.1 用户已确认（2026-10-09）

| # | 决策项 | 结论 |
|---|---|---|
| Q1 | 产品形态 | **集成进现有下载站**：新增 `/summarize` 页，复用 yt-dlp 与蓝金风格，一套代码一次部署 |
| Q2 | 大模型接入 | **OpenAI 兼容接口封装**：三个环境变量 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` 可切 DeepSeek / 通义 / 智谱 / Moonshot / Ollama / 本地 Ollama；默认接入幻城网安公益大模型网关 `https://api.hcnsec.cn/v1`，模型 `auto`（智能路由，一定可用） |
| Q3 | 无字幕视频 | **MVP 只处理有字幕视频**，抓不到给出明确可操作提示 |
| Q4 | MVP 输出 | **全选**：带时间戳章节大纲 + 核心要点（3-10 条 + 一句话总览）+ 思维导图 + AI 追问对话 |
| Q5 | 导出留存 | **Word / PDF 导出** |

### 3.2 我补充声明、用户未反驳的假设

1. Q5 只勾了 PDF/Word，我把「**复制 + 下载 Markdown**」作为基础能力一并做（成本近零，且是 DOCX 的上游产物）。
2. 用户本机已有或会自行申请 OpenAI 兼容 API Key；做成环境变量，未提供时页面给明确配置引导，不阻塞开发。

### 3.3 关键技术取舍（含理由）

| 取舍 | 选择 | 理由 |
|---|---|---|
| 代码组织 | 新建 `summarizer.py` 独立模块 | 总结逻辑约 350+ 行，混入 447 行的 `app.py` 会膨胀到 800 行，违背可读性；`app.py` 只加薄路由 |
| LLM 客户端 | 标准库 `urllib.request` 手写 | 现有依赖只有 flask + yt-dlp；SDK 带来传递依赖与版本锁定。OpenAI 兼容协议足够简单，SSE 解析约 60 行 |
| 思维导图 | 前端自研 **SVG 横向曲线导图**（自算布局 + 贝塞尔连线 + 分支配色 + 缩放/平移/折叠） | mermaid 需 CDN，离线不可用；纯 CSS 画不出平滑曲线，故用 SVG 自绘 |
| PDF 导出 | 前端 `window.print()` + `@media print` | Windows 上 weasyprint / xhtml2pdf 需 GTK 或编译，安装失败率高 |
| DOCX 导出 | 后端 `python-docx` | 纯 Python、跨 Windows 稳定，是唯一新增依赖 |
| 视频处理 | **不下载视频，只拉字幕轨** | 1 小时视频字幕通常 3-10 秒拿到，远快于下载视频再转写 |

---

## 四、技术选型与版本（2026-10 最新核对）

> 本节所有版本号与接口地址均于 **2026-10-09** 通过 Context7 官方文档与联网检索核实，避免写出过时代码。

### 4.1 依赖版本

| 依赖 | 最新版本（核实） | 本项目声明 |
|---|---|---|
| Flask | **3.1.3**（2026-02-19 发布，PyPI） | 沿用现有 `flask>=3.1,<4` ✅ 无需改 |
| yt-dlp | 频繁发版，靠启动自动更新 | 沿用现有 `yt-dlp>=2026.08.19` ✅ 无需改 |
| python-docx | **1.2.0**（2025-06-16 发布，PyPI，requires_python ≥3.9） | **新增** `python-docx>=1.2,<2` |

### 4.2 yt-dlp 字幕抓取参数（Context7 `/yt-dlp/yt-dlp` 官方 README 核实）

官方选项（原文）：
```
--write-subs            Write subtitle file
--write-auto-subs       Write automatically generated subtitle file (Alias: --write-automatic-subs)
--list-subs             List available subtitles of each video
--sub-format FORMAT     Subtitle format; accepts formats preference separated by "/", e.g. "srt" or "ass/srt/best"
--sub-langs LANGS       Languages of the subtitles to download (can be regex) or "all",
                        comma separated, e.g. --sub-langs "en.*,ja"; prefix "-" to exclude
```

官方源码中还确认了一个关键行为（`YoutubeDL._write_subtitles`）：当 `requested_subtitles` 为空时，字幕写入直接返回并打印 `[info] There are no subtitles for the requested languages` —— 这正是我们判断「无字幕」的依据。

本项目采用的最终命令：
```bash
yt-dlp --skip-download --no-playlist \
       --write-subs --write-auto-subs \
       --sub-langs "zh-Hans,zh-CN,zh,zh-TW,en.*" \
       --sub-format "vtt/srt/best" \
       --convert-subs srt \
       -o "<tmpdir>/sub.%(ext)s" \
       [--cookies cookies.txt] \
       <URL>
```
- **2026 实践补充**：`--convert-subs srt` 把各家吐出的 VTT/JSON 统一转成 SRT，解析器只需处理一种格式（该后处理器依赖 ffmpeg，本项目已装 ffmpeg 8.0.1，满足条件）。
- `--sub-langs` 中 `zh.*`/`en.*` 是**正则**，命中多轨时按优先级取第一条。
- 输出前缀固定为 `sub`，落盘后 glob `sub*.srt` 即可拿到文件。
- 复用现有 `cookie_args()`：B站部分 AI 字幕、登录态内容需要 cookie。

### 4.3 OpenAI 兼容接口协议（Context7 OpenAI API Reference 核实）

- 端点：`POST {BASE_URL}/chat/completions`
- 请求体：`{model, messages:[{role, content}], stream?, response_format?}`
- 流式：`stream: true` 时返回 SSE，每个事件形如 `data: {json}`，以 `data: [DONE]` 结束；终止 chunk 的 `finish_reason` 为 `stop`
- 非流式响应：`choices[0].message.content`
- 结构化输出：使用 `response_format={"type":"json_object"}`（DeepSeek / OpenAI / Ollama 均支持；为兼容性另做「提示词约束 + ```json 代码块抽取」兜底）

### 4.4 DeepSeek 模型与地址（官方文档 2026-10 核实，**重要修正**）

| 项 | 值 |
|---|---|
| base_url（OpenAI 格式） | `https://api.deepseek.com`（也可用 `https://api.deepseek.com/v1`，此处 `/v1` 与模型版本无关） |
| **当前模型名** | `deepseek-flash`（对应 DeepSeek-V4.1-Flash）、`deepseek-v4-pro`（对应 DeepSeek-V4-Pro-0813） |
| **已过时不建议用** | `deepseek-v4-flash`（官方注明：模型已下线，请求会被转发到 V4.1-Flash 并按 Flash 计费）；`deepseek-chat`（已不在当前模型与价格表中） |
| 上下文长度 | **1M** |
| 最大输出 | 384K |
| 能力 | JSON Output ✅、Tool Calls ✅、Responses API ✅、图像理解（仅 flash） |
| 价格（百万 tokens，缓存未命中） | flash 输入 ¥1（空闲）/ ¥2（高峰）；输出 ¥4 / ¥8。pro 输入 ¥4.5 / ¥9；输出 ¥13.5 / ¥27 |
| 并发限制 | flash 2500、pro 500 |

> **对方案的直接影响**：上下文 1M，意味着 1 小时视频字幕（约 1-2 万汉字 ≈ 2-3 万 token）**完全可一次整篇输入**，无需强制分块。因此把 map-reduce 降级为「超长文本 / 小上下文模型（如 Ollama）」的兜底路径，默认走整篇单次调用 —— 更快、更便宜、时间戳连贯性更好。

### 4.5 其他厂商 OpenAI 兼容地址（文档只给示例，接入时以各家官方最新文档为准）

| 厂商 | 兼容 base_url（示例） | 备注 |
|---|---|---|
| DeepSeek | `https://api.deepseek.com` | 见 4.4 |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4/` | 官方兼容接口路径与 OpenAI 略有差异，接入前核对官方最新文档 |
| 通义千问 Qwen | DashScope **兼容模式**地址 | 与原生 DashScope URL 不同，需用兼容模式地址 |
| Moonshot Kimi | `https://api.moonshot.cn/v1` | 以官方为准 |
| 硅基流动 | `https://api.siliconflow.cn/v1` | 聚合多家开源模型 |
| 本地 Ollama | `http://127.0.0.1:11434/v1` | 离线免费，质量较弱 |

> 结论：封装成 `LLM_BASE_URL` + `LLM_API_KEY` + `LLM_MODEL` 三个环境变量是正确设计，能吸收各家地址/模型名的一年多次变更。

---

## 五、架构设计

```mermaid
flowchart TB
  U[用户浏览器] -->|粘贴链接| P[summarize.html + summary.js]
  P -->|POST /api/summarize| A[Flask app.py 路由层]
  P -->|GET /api/summary/status/id| A
  P -->|POST /api/summary/ask SSE| A
  P -->|POST /api/summary/export| A
  A -->|后台线程| S[summarizer.py]
  S -->|subprocess| YT[yt-dlp 只拉字幕]
  YT --> VTT[sub*.srt 字幕文件]
  S -->|parse_srt| CUES[(start,end,text) 序列]
  CUES -->|整篇 or 分块| LLM[OpenAI 兼容 /chat/completions]
  LLM --> JSON[overview / chapters / keypoints / mindmap]
  JSON --> DOCX[python-docx 导出]
  JSON --> P
  CUES --> ASK[追问上下文]
  ASK -->|SSE 流式| P
```

**数据流**：粘贴 URL → 后台线程 yt-dlp 抓字幕 → 解析 SRT →（超长则分块 map-reduce）→ 单次 LLM 调用产出严格 JSON → 前端分区渲染（总览 / 大纲 / 要点 / 导图）→ 可追问、可导出 MD / DOCX / PDF。

**任务模型**：沿用现有 `jobs` 内存字典 + `threading.Thread` + 前端轮询，不引入数据库；`cleanup_worker()` 按 `JOB_TTL` 统一回收。LLM 调用使用**独立信号量**（默认 3），与下载信号量 `download_slots` 分离。

---

## 六、关键接口契约

```python
# GET  /api/llm/config             -> {configured, base_url, model}        # 不回传密钥
# GET  /api/llm/models             -> {"models": [...]} | {"error": "..."} # GET {base}/models
# POST /api/summarize              {url} -> {job_id}                       # 校验 http(s)，后台线程跑
# GET  /api/summary/status/<job_id> -> {status, stage, stage_text, percent, error, meta, result, url}
# POST /api/summary/ask            {job_id, question, history[]} -> SSE     # 见下
# POST /api/summary/export         {job_id, format:"md"|"docx"} -> 文本/附件
```

**`/api/summary/ask` 的 SSE 事件格式**（`summary.js` 的 `pollAsk` 逐条解析）：
```
data: {"delta": "片段文本"}        # 流式增量，可能多条
data: {"delta": "", "done": true} # 正常结束
data: {"error": "错误摘要"}        # 出错（不回显堆栈/密钥）
```

**`/api/summary/export` 响应**：`format=md` 返回 `text/markdown` 正文，文件名经 `content_disposition()` 处理（中文名兼容，避免 Werkzeug 抛 `UnicodeEncodeError`）；`format=docx` 后端 `python-docx` 生成并 `send_file` 下载。

**`/api/summary/status` 与前端轮询契约**：`status` ∈ `running` / `done` / `error`；`stage`（仅 running 有意义）∈ `fetching`（抓取字幕）→ `parsing`（解析时间轴）→ `summarizing`（生成总结）；失败时 `status=error` 且带 `error` 文案。`result` 字段见下方 JSON 契约；`meta` 见上。

**模型输出的结构化结果**（前端渲染的唯一数据契约）：

```json
{
  "overview": "一句话总览",
  "chapters": [
    {"start": 0, "end": 320, "title": "章节标题", "points": ["要点1", "要点2"]}
  ],
  "keypoints": ["核心知识要点 1", "核心知识要点 2"],
  "mindmap": "- 主题\n  - 子主题\n    - 叶子节点",
  "degraded": false
}
```

- `degraded: true` 表示结构化解析最终失败、退回纯文本（`overview` 为截断原文、`chapters`/`keypoints` 为空），前端应给出"总结可能不完整"的提示，**绝不白屏**。
- 配套的 `meta`（来自 `fetch_meta`，随 status 一并返回）：`title` / `thumbnail` / `duration` / `uploader` / `webpage_url`，前端用于结果卡片头部与"跳原视频 `&t=<秒>`"链接。

**环境变量**（全部可被环境变量覆盖，定义见 `summarizer.py` 顶部）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `LLM_BASE_URL` | `https://api.hcnsec.cn/v1` | OpenAI 兼容地址；幻城网安公益网关为默认（可改 DeepSeek / 智谱 / Ollama 等） |
| `LLM_API_KEY` | 空 | 未提供时页面显示配置引导；配置后 `llm_configured()` 返回 True |
| `LLM_MODEL` | `auto` | 网关智能路由（一定可用）；固定模型请填控制台「模型广场」准确 ID（如 `deepseek-v3.2` / `glm-5.1`） |
| `LLM_TIMEOUT` | `180` | 单次请求超时秒数 |
| `LLM_MAX_TOKENS` | `8192` | 单次输出最大 token；网关文档提示过小会被截断，默认给足 |
| `SUMMARY_CHUNK_CHARS` | `60000` | 字幕超过该字符数才启用分块 map-reduce |
| `SUMMARY_MAX_CONCURRENCY` | `3` | LLM 并发信号量（与下载信号量分离） |
| `ASK_CONTEXT_CHARS` | `60000` | 追问时可附带的完整字幕上限；超过则只给总结，不附全文 |
| `SUB_LANGS` | `zh-Hans,zh-CN,zh,zh-TW,en.*` | 字幕语言优先级（yt-dlp 正则），首选项拿不到再退化为 `all` |
| `COOKIE_FILE` | `<项目根>/cookies.txt` | 登录态字幕所需 Cookie（Netscape 格式），缺省即项目根 `cookies.txt` |

---

## 七、实施要点（防返工清单）

1. **字幕格式兼容**：`--convert-subs srt` 统一成 SRT 后再解析；解析器仍需容错 VTT（`00:00:01.000 -->`）以防转换失败。
2. **去重**：自动字幕（尤其 YouTube ASR）存在大量滚动重复前缀，必须按规范化文本去重；合并时长 <0.5s 的碎片段。
3. **时间戳贯穿全流程**：解析为 `(start, end, text)` → 送模型时**每段保留时间戳前缀** → 提示词要求输出 `start` 秒数 → 前端渲染为可点击的时间轴（跳原视频 `&t=<秒>`）。这是竞品最核心的体验点。
4. **整篇优先**：默认整篇单次调用（DeepSeek 1M 上下文）；仅当字符数 > `SUMMARY_CHUNK_CHARS` 或用户用小上下文模型时才启用分块；分块按时间点切、块间保留重叠、并发 map 后单次 reduce。
5. **结构化输出兜底**：优先 `response_format=json_object`；解析失败自动重试 1 次并收紧提示；仍失败则降级为纯文本展示，**绝不白屏**。
6. **Windows 编码**：子进程统一走现有 `child_env()`（`PYTHONIOENCODING=utf-8`）；读写字幕文件显式 `encoding="utf-8"`。
7. **文件名安全**：沿用现有过滤 `r'\/:*?"<>|'` 与 100 字截断。
8. **错误脱敏**：只回传 HTTP 状态码与简短错误摘要，**绝不回显 API Key 或完整请求体**。
9. **合规**：总结页沿用现有版权提示，明确「仅用于个人学习」。
10. **向后兼容**：不改动任何现有接口契约，仅在 `index.html` 导航与页脚追加入口。

---

## 八、页面规划：`/summarize`（桌面 1440 / 移动 390）

沿用站内「现代科技渐变 + 玻璃质感卡片 + 蓝色主色 `#1777FF` + 金色强调 `#FFB020`」设计语言，结果区增加知识感与阅读舒适度。

- **导航栏**：与首页完全一致（首页 / **AI 总结** / 定价 / 支持平台 + 金色「开通会员」胶囊 + 移动端汉堡菜单），「AI 总结」为高亮态。
- **Hero 输入区**：深蓝渐变光晕背景；居中大标题「一分钟读懂一小时视频」+ 灰色副标题；胶囊输入框（链接图标 + 占位文案 + 蓝色胶囊「开始总结」）；右侧小字提示当前模型，未配置时显示配置指引。
- **流水线进度区**：四段横向步骤条（抓取字幕 → 解析时间轴 → 分段理解 → 生成大纲），当前步高亮发光、已完成打勾；失败时该步变红并给出可操作提示。
- **四段式结果区**：
  1. 一句话总览卡片（大字号 + 左侧蓝色竖条强调）
  2. 章节大纲时间轴（时间戳胶囊 + 标题 + 要点列表，时间戳可点击跳回原视频）
  3. 核心要点卡片网格（编号 + 要点）
  4. 思维导图（ProcessOn 风格横向曲线图：SVG 自绘贝塞尔连线、分支配色、可缩放平移、点击节点折叠）
  桌面用锚点 Tab 切换，移动端纵向堆叠。
- **导图实现位置**（改样式/交互先看这里）：`summary.js` 中 `parseMindmap(text)` 把 Markdown 缩进列表解析为树 → `renderMindmap(text)` 用 SVG 自算布局（按层级分列、贝塞尔曲线连线、各分支配色）渲染 → `mmSetup()` 绑定工具栏（缩放 `data-mm=in/out`、平移拖拽、`fit` 适应、`reset` 1:1、点击节点折叠 `toggleNode`）。数据契约即 `result.mindmap` 那段缩进文本；连线/配色常量集中在 `renderMindmap` 顶部。
- **AI 追问对话区**：气泡式对话（用户右对齐蓝色、AI 左对齐浅灰卡片），流式打字机效果，底部常用问题快捷 chip。
- **导出栏 + 页脚**：复制 / Markdown / Word / PDF 四个胶囊按钮（PDF 走打印）；页脚沿用版权声明。
- **微动效**：卡片渐入上浮、按钮 hover 上移、进度条流动、导图节点 hover 高亮。

---

## 九、文件变更清单

```
d:/ai/hj-video-downloader/
├── app.py                     # [DONE] 新增 6 条路由（页面 /summarize、/api/llm/config、
│                              #   /api/llm/models、/api/summarize、/api/summary/status/<id>、
│                              #   /api/summary/ask、/api/summary/export）；复用 jobs / threading / cleanup_worker
├── summarizer.py              # [DONE] LLM 客户端（urllib + SSE）、字幕抓取与 SRT/VTT 解析、
│                              #   整篇/分块总结、结构化结果校验、Markdown/DOCX 导出、Whisper 预留接口
├── requirements.txt           # [DONE] 追加 python-docx>=1.2,<2
├── templates/
│   ├── index.html             # [DONE] 导航 .nav__links / .mobile-menu / 页脚追加「AI 总结」入口
│   └── summarize.html         # [DONE] 总结页（含导图工具栏与画布容器）
├── static/
│   ├── css/style.css          # [DONE] 总结页样式、思维导图连线、@media print 打印样式
│   ├── js/summary.js          # [DONE] 提交、进度轮询、四段渲染、SVG 导图（布局/缩放/折叠）、SSE 追问、导出
│   └── js/app.js              # [DONE] 视频卡片追加「去总结」跳转按钮（最小改动）
├── llm_config.example.bat     # [DONE] 环境变量配置示例：set LLM_* 后调用 run.bat
├── README.md                  # [DONE] 新增「AI 视频总结」章节
└── docs/AI视频总结-设计文档.md  # [DONE] 本文档
```

---

## 十、开发任务拆分

> 状态：**全部已完成（2026-10-10，随提交 71bde4b 上线 origin/main）**。

| # | 任务 | 交付物 | 状态 |
|---|---|---|---|
| 1 | 新建 `summarizer.py`：字幕抓取、SRT/VTT 解析去重、LLM 客户端（urllib + SSE）、整篇/分块总结与提示词 | 模块 + 单元自测 | ✅ |
| 2 | `app.py` 新增 6 条总结路由（`/api/llm/config`、`/api/llm/models`、`/api/summarize`、`/api/summary/status`、SSE `/api/summary/ask`、`/api/summary/export`），复用 jobs 与后台线程模型 | 接口可用 | ✅ |
| 3 | 新建 `templates/summarize.html` + `static/js/summary.js`：输入、流水线进度、四段结果、ProcessOn 风格 SVG 导图、SSE 追问、导出 | 页面可用 | ✅ |
| 4 | `style.css` 追加总结页样式与 `@media print` 打印样式 | 视觉一致 | ✅ |
| 5 | 入口接入（`index.html` 导航、卡片按钮）与文档（`requirements.txt`、`README.md`、`llm_config.example.bat`） | 一体化 | ✅ |
| 6 | 冒烟验证：接口、追问、导出、桌面与移动端 | 验证通过 | ✅ |
| 7 | 思维导图重构为 ProcessOn 风格横向曲线图（SVG 自绘 + 工具栏） | 视觉升级 | ✅ |

---

## 十一、风险与二期预留

| 项 | 现状 | 二期方向 |
|---|---|---|
| 无字幕视频 | MVP 只提示「无可用字幕」 | `summarizer.py` 预留 `whisper_fallback()` 接口，接 faster-whisper 本地转写 |
| 画面理解 | 不做 | 抽关键帧 + 视觉模型（BibiGPT Pro 卖点） |
| 批量总结 | 不做 | 复用现有批量下载线程模型 |
| 历史留存 | 纯内存，随 job 过期 | 本地 SQLite + 历史列表页 |
| 长视频并发 | 单任务串行 | 分块并发 map（已预留 `SUMMARY_MAX_CONCURRENCY`） |

---

## 十三、代码模块地图（改动 / 扩展速查）

### summarizer.py 函数职责
| 函数 | 职责 | 常见改动场景 |
|---|---|---|
| `fetch_meta(url)` | yt-dlp `-j` 取标题/时长/封面/作者 | 想多抓字段 |
| `fetch_subtitle(url)` | 抓字幕：先中文轨再 `all`，失败抛 `SummaryError` | 调整语言策略 |
| `_no_subtitle_reason(log)` | yt-dlp 报错分类为「需登录 / 人机校验 / 网络 / 真无字幕」 | 新增平台报错匹配 |
| `parse_subtitle` / `normalize_cues` | SRT/VTT 解析 + 去重 + 短句合并 | 解析质量调优 |
| `cues_to_transcript(cues)` | 时间轴 → `[mm:ss] 文本` 送模型文本 | 改提示词输入格式 |
| `chat` / `chat_stream` / `list_models` | OpenAI 兼容客户端（urllib，SSE） | 换网关 / 加模型能力 |
| `build_summary_messages` / `build_map_messages` / `build_reduce_messages` | 提示词 | 调总结质量 |
| `summarize(...)` | 整篇优先，超长退化为分块 map-reduce | 改总结策略 |
| `normalize_result(data)` | 模型输出 → 前端契约（缺字段补默认） | 改输出结构 |
| `to_markdown` / `to_docx` | 导出 | 改导出样式 |
| `run_summary(job, url)` | 流水线（抓→解析→总结），改写 job 字典 | 加阶段 / 埋点 |
| `whisper_fallback(url)` | **二期预留**：无字幕 → 本地语音转写 | 接 faster-whisper |

### app.py 路由（文件末尾「AI 视频总结」段）
- 页面：`/summarize`
- 配置：`/api/llm/config`、`/api/llm/models`
- 任务：`/api/summarize`、`/api/summary/status/<id>`、`/api/summary/ask`(SSE)、`/api/summary/export`
- 注入点（避免循环导入）：`summarizer.configure(ytdlp=..., cookie_args=..., child_env=...)` 在 `app.py` 启动时调用

### 前端（templates/summarize.html + static/js/summary.js + static/css/style.css）
- 输入/进度/四段渲染/导出：`submitSummary` → `pollStatus` → `renderResult`（含 `renderTimeline` / `renderKeypoints` / `renderMindmap`）
- 追问 SSE：`askFlow` → `pollAsk`（解析 `{"delta"}` / `{"done"}` / `{"error"}`）
- 导图：`parseMindmap` → `renderMindmap`（SVG）→ `mmSetup`（工具栏 + 拖拽 + 折叠）
- 样式：`.mindmap` / `.mm-*` / `@media print` 集中在 `style.css`

---

## 十二、参考资料

- BibiGPT：https://bibigpt.co/ ｜ 定价机器可读版：https://bibigpt.co/pricing.md ｜ 文档：https://docs.bibigpt.co/
- NoteGPT B站总结器：https://notegpt.io/cn/bilibili-summarizer ｜ 定价：https://notegpt.io/cn/pricing
- yt-dlp 官方字幕选项（Context7 `/yt-dlp/yt-dlp`）：`--write-subs` / `--write-auto-subs` / `--sub-langs` / `--sub-format` / `--convert-subs`
- OpenAI Chat Completions（Context7 `/websites/developers_openai_api_reference_resources`）：SSE 流式、`response_format`
- DeepSeek 模型与价格（官方，2026-10 核实）：https://api-docs.deepseek.com/zh-cn/quick_start/pricing
- python-docx 文档（Context7 `/websites/python-docx_readthedocs_io_en`）：`add_heading` / `add_paragraph(style='List Bullet')` / `save`
- PyPI 版本核实：Flask 3.1.3、python-docx 1.2.0
