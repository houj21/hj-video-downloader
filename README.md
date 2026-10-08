# HJ 视频下载

基于 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 的多平台视频下载网站。粘贴链接即可解析、选择清晰度并下载为 MP4 或 MP3，移动端浏览器同样可用。界面为定制设计的现代渐变风格（蓝色主色 + 金色付费强调），带会员/定价展示页（占位，未接支付）。

> 本项目为学习与自用导向的开源实践，基座为 [ReClip](https://github.com/averygan/reclip)（MIT License）。请仅下载你拥有合法权利或已获授权的内容，并遵守各平台服务条款与当地法律法规；请勿用于下载付费、受版权保护或未经授权的内容，也不要高频请求以免触发平台风控。因使用本工具产生的任何风险由使用者自行承担。

## 功能

- **链接解析**：粘贴一个或多个视频链接（支持播放列表 / 合集自动展开），获取标题、封面、时长、上传者与可选清晰度
- **多平台支持**：yt-dlp 支持的 1000+ 站点（YouTube、哔哩哔哩、抖音、微博、小红书、Twitter/X、Instagram 等），首页含平台能力说明区块
- **下载能力**：MP4 视频 / MP3 音频切换、按清晰度选择、单条与批量下载、批量任务自动打包为 zip
- **实时进度**：后台线程下载，前端队列展示实时百分比进度条
- **移动端适配**：390px 视口单列布局、汉堡菜单、大按钮，下载完成直接触发浏览器保存
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

## 目录结构

```
├── app.py               # Flask 后端（单文件）：解析 / 下载 / 进度 / 批量打包 / 定时清理
├── requirements.txt     # flask、yt-dlp
├── run.bat              # Windows 一键启动脚本
├── templates/
│   ├── index.html       # 首页：Hero 输入区、解析结果、下载队列、支持平台、会员区块
│   └── pricing.html     # 定价页：套餐卡片、权益对比、FAQ
├── static/
│   ├── css/style.css    # 设计系统（#1777FF 主色 / #FFB020 金色强调 / 渐变 Hero）
│   ├── js/app.js        # 解析、清晰度选择、批量下载、进度轮询、历史记录
│   └── favicon.svg
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

## 技术栈

- **后端**：Python 3.13 + Flask（单文件，无数据库），`subprocess` 调用 yt-dlp CLI
- **下载内核**：yt-dlp + ffmpeg（音视频合并、MP3 抽取）
- **前端**：原生 HTML / CSS / JS，无构建步骤；移动端优先的响应式设计
