# HJ 视频下载

基于 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 的多平台视频下载网站。粘贴链接即可解析、选择清晰度并下载为 MP4 或 MP3，移动端浏览器同样可用。界面为定制设计的现代渐变风格（蓝色主色 + 金色付费强调），带会员/定价展示页（占位，未接支付）。

> 本项目为学习与自用导向的开源实践，基座为 [ReClip](https://github.com/averygan/reclip)（MIT License）。请仅下载你拥有合法权利或已获授权的内容，并遵守各平台服务条款与当地法律法规；请勿用于下载付费、受版权保护或未经授权的内容，也不要高频请求以免触发平台风控。因使用本工具产生的任何风险由使用者自行承担。

## 功能

- **链接解析**：粘贴一个或多个视频链接（支持播放列表 / 合集自动展开），获取标题、封面、时长、上传者与可选清晰度
- **多平台支持**：yt-dlp 支持的 1000+ 站点（YouTube、哔哩哔哩、抖音、微博、小红书、Twitter/X、Instagram 等），首页含平台能力说明区块
- **下载能力**：MP4 视频 / MP3 音频切换、按清晰度选择、单条与批量下载、批量任务自动打包为 zip
- **实时进度**：后台线程下载，前端队列展示实时百分比进度条
- **移动端适配**：390px 视口单列布局、汉堡菜单、大按钮，下载完成直接触发浏览器保存
- **AI 视频总结**：粘贴链接自动生成一句话总览、带时间戳的章节大纲、核心要点与思维导图，可基于内容继续追问，并导出 Markdown / Word / PDF
- **付费引导（占位）**：首页会员权益区块 + 定价页（三档套餐、权益对比、FAQ），支付通道未接入
- **免运维**：无数据库，任务存内存；`downloads/` 目录自动定时清理（默认 30 分钟），yt-dlp 启动时自动更新

## 快速开始

环境要求：Windows + [Python 3.13](https://www.python.org/downloads/)（`py -3.13` 可用）+ [ffmpeg](https://www.gyan.dev/ffmpeg/builds/)（在 PATH 中）。

```bat
:: 双击 run.bat，或命令行执行：
run.bat
```

脚本首次运行会自动创建 `.venv` 虚拟环境并安装依赖（清华镜像加速），随后启动服务。浏览器访问 <http://127.0.0.1:8899>。

手动方式：

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

## 使用方法

1. 打开 <http://127.0.0.1:8899>，在搜索框粘贴视频链接（多个链接用空格分隔）
2. 点击「解析」，选择 MP4 / MP3 与清晰度
3. 点击「下载 MP4」（多个结果可「全部下载」），在下方下载队列查看进度
4. 完成后点击「保存到本地」，文件由浏览器保存到本机

## 配置项（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `PORT` / `HOST` | `8899` / `127.0.0.1` | 服务监听地址 |
| `MAX_CONCURRENT` | `3` | 并发下载数上限 |
| `FILE_TTL` | `1800` | 下载文件保留秒数（超时自动清理） |
| `MAX_DIR_BYTES` | `2 GiB` | 下载目录容量上限（超限按最旧删除） |
| `DOWNLOAD_TIMEOUT` | `900` | 单任务下载超时秒数 |
| `COOKIE_FILE` | 项目根 `cookies.txt` | Netscape 格式 Cookie 文件，用于登录内容（存在即生效） |
| `SKIP_YTDLP_UPDATE` | 未设置 | 设为 `1` 跳过启动时的 yt-dlp 自动更新 |
| `LLM_API_KEY` | 空 | 大模型密钥；**未设置时总结页只显示配置引导**，下载功能不受影响 |
| `LLM_BASE_URL` | `https://api.hcnsec.cn/v1` | OpenAI 兼容接口地址（默认幻城网安公益网关；可换 DeepSeek / 智谱 / 本地 Ollama） |
| `LLM_MODEL` | `auto` | 模型名。`auto` = 网关智能路由；也可填模型广场里的准确 ID |
| `LLM_TIMEOUT` | `180` | 单次大模型请求超时秒数，长视频可调大 |
| `SUMMARY_CHUNK_CHARS` | `60000` | 字幕超过该字符数才启用分块 map-reduce（默认整篇一次输入） |
| `SUMMARY_MAX_CONCURRENCY` | `3` | 分块总结时的并发上限 |
| `ASK_CONTEXT_CHARS` | `60000` | 追问时附带完整字幕的字符上限，超过则只带总结 |

## 目录结构

```
├── app.py               # Flask 后端（单文件）：解析 / 下载 / 进度 / 批量打包 / 定时清理 / 总结路由
├── summarizer.py        # AI 总结模块：字幕抓取与解析、大模型客户端、整篇与分块总结、导出
├── requirements.txt     # flask、yt-dlp、python-docx
├── run.bat              # Windows 一键启动脚本
├── llm_config.example.bat # 大模型环境变量配置示例（复制为 llm_config.bat 后填 Key）
├── templates/
│   ├── index.html       # 首页：Hero 输入区、解析结果、下载队列、支持平台、会员区块
│   ├── summarize.html   # AI 总结页：输入区、流水线进度、四段式结果、追问、导出
│   └── pricing.html     # 定价页：套餐卡片、权益对比、FAQ
├── static/
│   ├── css/style.css    # 设计系统（#1777FF 主色 / #FFB020 金色强调 / 渐变 Hero / 打印样式）
│   ├── js/app.js        # 解析、清晰度选择、批量下载、进度轮询、历史记录
│   ├── js/summary.js    # 总结提交、进度轮询、结果渲染、思维导图、SSE 追问、导出
│   └── favicon.svg
├── docs/                # 设计文档（AI 总结的竞品调研与方案设计，供溯源）
└── downloads/           # 下载暂存目录（自动清理，不入库）
```

## API

与上游 ReClip 保持兼容，仅做可选字段扩展：

```
POST /api/info            {url}                    -> {title, thumbnail, duration, uploader, formats:[{id,label,height}]}
POST /api/playlist        {url}                    -> {urls:[...]}
POST /api/download        {url|urls, format, format_id?, title?}
                                                   -> {job_id, batch}
GET  /api/status/<job_id>                          -> {status, error?, filename?, percent?, current?, total?}
GET  /api/file/<job_id>                            -> 附件文件流（批量任务为 zip）
```

AI 总结相关（新增）：

```
GET  /api/llm/config                               -> {configured, base_url, model}
POST /api/summarize        {url}                   -> {job_id}
GET  /api/summary/status/<job_id>                  -> {status, stage, stage_text, percent, error?, meta?, result?}
POST /api/summary/ask      {job_id, question, history[]} -> text/event-stream（SSE 流式）
POST /api/summary/export   {job_id, format:"md"|"docx"} -> 附件文件流
```

## AI 视频总结

打开 <http://127.0.0.1:8899/summarize>，粘贴视频链接即可生成：

1. **一句话总览** —— 30 秒判断这个视频值不值得看
2. **带时间戳的章节大纲** —— 点击时间戳可跳回原视频对应位置
3. **核心知识要点** —— 3-10 条，快速抓住重点
4. **思维导图** —— 可视化整视频的知识结构
5. **继续追问** —— 基于字幕上下文多轮提问，流式输出
6. **导出** —— 复制 / Markdown / Word / PDF（PDF 走浏览器打印，选择「另存为 PDF」）

### 配置大模型（必做）

默认接入 **新疆幻城网安科技公益大模型安全网关**（<https://api.hcnsec.cn/>，基于 NewAPI 的 OpenAI 兼容网关，注册送免费额度）。

1. 打开 <https://api.hcnsec.cn/console> 注册登录 → 左侧「令牌」→「添加令牌」→ 复制 `sk-` 开头的密钥（**只显示一次**）
2. 复制 `llm_config.example.bat` 为 `llm_config.bat`，填入 `LLM_API_KEY`
3. 双击 `llm_config.bat` 启动

| 配置项 | 值 |
|---|---|
| `LLM_BASE_URL` | `https://api.hcnsec.cn/v1` |
| `LLM_MODEL` | `auto`（智能路由，一定可用） |
| 鉴权 | `Authorization: Bearer sk-xxx`（标准 OpenAI 方式） |

**想固定某个模型**：在控制台「模型广场」挑一个，把准确 ID 填到 `LLM_MODEL`，例如
`deepseek-v3.2` / `deepseek-v4-pro` / `glm-5.1` / `qwen3.6-plus` / `kimi-k2.6`。
不确定有哪些可用时，启动服务后访问：

```
http://127.0.0.1:8899/api/llm/models
```

> 换成 DeepSeek 官方、智谱或本地 Ollama 也只需改 `LLM_BASE_URL` 与 `LLM_MODEL` 两行。
> 若某个上游模型不支持结构化 JSON 输出，程序会自动去掉该参数重试，不会直接失败。

未配置时总结页会显示配置引导，**下载功能不受影响**。

### 支持的视频

- 复用 yt-dlp 的 1000+ 站点，只要有字幕即可（B站、YouTube、课程、播客、演讲等）
- 优先取中文字幕，取不到再回退到其他语言
- **当前版本仅支持有字幕的视频**：无字幕会给出明确提示，语音转写（Whisper）为二期功能

### ⚠️ 关于 Cookie（实测结论，2026-10）

部分平台**必须登录**才能拿到字幕，否则会报「需要登录」而不是「没有字幕」：

| 平台 | 未登录时的表现 |
|---|---|
| 哔哩哔哩 | `Subtitles are only available when logged in` —— 必须配置 Cookie |
| YouTube | 常触发 `Sign in to confirm you're not a bot` —— 需配置 Cookie |

配置方式：导出浏览器的 Netscape 格式 Cookie，保存为项目根目录的 `cookies.txt`（或设置 `COOKIE_FILE` 环境变量指向它），服务启动时会自动加载并提示 `使用 Cookie 文件`。该文件已被 `.gitignore` 排除，不会误提交。

> 视频**下载**功能不受此限制影响（未登录只是拿不到最高清晰度）。

### 成本与隐私

- 视频本体**不下载**，只拉取字幕轨，通常 3-10 秒即可拿到
- 字幕与总结都在本机内存中处理，随任务过期（默认 1 小时）自动清理
- 费用即大模型 token 费：1 小时视频约 1-2 万字，DeepSeek 量级单次约几分钱

## 技术栈

- **后端**：Python 3.13 + Flask（单文件，无数据库），`subprocess` 调用 yt-dlp CLI
- **下载内核**：yt-dlp + ffmpeg（音视频合并、MP3 抽取）
- **AI 总结**：`summarizer.py`（字幕抓取与解析 + 标准库 `urllib` 实现的 OpenAI 兼容客户端，含 SSE 流式）
- **导出**：`python-docx`（Word）、前端 Blob（Markdown）、浏览器打印（PDF）
- **前端**：原生 HTML / CSS / JS，无构建步骤；移动端优先的响应式设计
