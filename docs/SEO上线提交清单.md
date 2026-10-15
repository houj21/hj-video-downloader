# SEO 上线提交清单

本文档说明《万能视频下载总结器》（HJ 视频下载）已完成的 SEO 改造，以及**正式部署上线后需要人工执行的步骤**。

---

## 一、已完成的技术改造（代码层面）

### 1. 统一 SEO 元信息引擎

| 文件 | 作用 |
|---|---|
| `seo.py` | 全站 TDK / canonical / robots / Open Graph / Twitter Card / JSON-LD / robots.txt / sitemap.xml 的唯一数据源 |
| `seo_content.py` | 读取 `data/seo` 下的 JSON 内容数据（进程内缓存） |
| `templates/seo/head.html` | Meta 标签片段，被所有页面 `include` |
| `templates/seo/nav.html`、`footer.html`、`download_widget.html` | 新增页面复用的公共片段 |

页面不再硬编码 TDK：每个页面的 `<title>`、`<meta name="description">` 都由 `seo.py` 按请求路径生成。

### 2. 每个页面都具备的标签

- `title` / `description` / `keywords`（百度、360、搜狗仍参考 keywords）
- `canonical`（避免 127.0.0.1 / 域名 / 带参数 URL 造成重复内容）
- `robots`（默认 `index, follow, max-image-preview:large`；未知路径自动 `noindex`）
- Open Graph：`og:type / title / description / image / image:alt / url / site_name / locale`
- Twitter Card：`summary_large_image`
- Schema.org `itemprop`：`name / description / image`
- JSON-LD：详见下表

| 页面 | JSON-LD 类型 |
|---|---|
| `/` 首页 | Organization + WebSite + SoftwareApplication |
| `/summarize` | WebPage + BreadcrumbList |
| `/pricing` | WebPage + BreadcrumbList |
| `/faq` | WebPage + FAQPage + BreadcrumbList |
| `/guides` | WebPage + ItemList + BreadcrumbList |
| `/guides/<slug>` | Article + BreadcrumbList |
| `/xxx-video-download` | WebPage + FAQPage + BreadcrumbList |
| 未知路径（404） | WebPage + BreadcrumbList，robots 输出 `noindex, follow` |

### 3. 新增页面

| 类型 | 路径示例 | 数量 |
|---|---|---|
| 平台长尾落地页 | `/bilibili-video-download`、`/youtube-video-download`、`/douyin-video-download`、`/xiaohongshu-video-download`、`/weibo-video-download`、`/kuaishou-video-download`、`/twitter-video-download`、`/instagram-video-download` | 8 |
| 使用指南 | `/guides` + `/guides/how-to-download-online-videos` 等 | 1 + 4 |
| 常见问题 | `/faq` | 1 |
| 404 页 | 任意不存在路径 | 1 |

### 4. 爬虫配置

- `/robots.txt`：允许抓取 HTML 与静态资源，**禁止抓取 `/api/`**，末尾自动带 Sitemap 地址
- `/sitemap.xml`：自动生成，收录全部可索引页面（当前 17 条 URL）

### 5. 内容数据可维护

内容全部放在 `data/seo/` 下，**改文案不需要动 Python 代码**：

```
data/seo/faq.json                 常见问题页
data/seo/guides/_index.json       使用指南索引页
data/seo/guides/<slug>.json       单篇指南
data/seo/platforms/<slug>.json    平台落地页
```

新增一个平台落地页 = 复制一个 JSON 文件、改内容、重启服务（路由会自动注册）。

> 注意：JSON 里每个平台/文章的 `title` 与 `description` 必须唯一，否则会被判定为重复内容。

---

## 二、部署时必须做的一件事

所有绝对 URL（canonical、og:url、sitemap）都由环境变量 `SEO_BASE_URL` 决定，**默认为本地开发地址**：

```
SEO_BASE_URL=https://你的域名
```

例如在 Windows 启动脚本中设置：

```bat
set SEO_BASE_URL=https://www.yourdomain.com
set HOST=0.0.0.0
set PORT=8899
python app.py
```

可选环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `SEO_BASE_URL` | `http://127.0.0.1:8899` | 站点对外根地址 |
| `SEO_LASTMOD` | `2026-10-15` | sitemap 的 lastmod |
| `SEO_OG_IMAGE` | `/static/img/og-cover.png` | OG 分享图路径 |

---

## 三、上线后人工执行清单

### 3.1 部署当天（必做）

- [ ] 配置 `SEO_BASE_URL` 为正式域名，重启服务
- [ ] 全站启用 HTTPS，并做 HTTP → HTTPS 的 301 跳转（搜索引擎口径不一致会分散权重）
- [ ] 确定主域口径（www 或非 www 二选一），另一个做 301 跳转
- [ ] 访问 `/robots.txt` 与 `/sitemap.xml`，确认里面的域名是正式域名

### 3.2 提交到各大搜索引擎

| 平台 | 地址 | 操作 |
|---|---|---|
| Google Search Console | https://search.google.com/search-console | 添加站点 → 提交 sitemap → 用 URL 检查工具测试首页抓取效果 |
| Bing Webmaster Tools | https://www.bing.com/webmasters | 添加站点 → 提交 sitemap（同时覆盖 Yahoo、DuckDuckGo 部分流量） |
| 百度搜索资源平台 | https://ziyuan.baidu.com | 验证站点 → 资源提交 →「普通收录」提交 sitemap，并用「API 主动推送」提交新页面 |
| 360 站长平台 | https://zhanzhang.so.com | 添加站点 → 提交 sitemap |
| 搜狗站长平台 | https://zhanzhang.sogou.com | 添加站点 → 提交 sitemap |
| 神马搜索 | https://zhanzhang.sm.cn | 面向移动端，建议一并提交 |

> 百度对 JS 渲染支持较弱，本项目是 Flask 服务端渲染（内容在 HTML 源码里），这一点天然占优，建议优先做百度主动推送。

### 3.3 结构化数据与富摘要验证

- [ ] Google Rich Results Test：https://search.google.com/test/rich-results
      分别测试 `/`（SoftwareApplication）、`/faq` 与任意落地页（FAQPage）、`/guides/<slug>`（Article）
- [ ] Schema.org Validator：https://validator.schema.org/

### 3.4 社交分享验证

- [ ] 微信：把链接发到文件传输助手，确认分享卡片标题/描述/图片正常（`og-cover.png` 为 1200×630）
- [ ] 需要更精美的带中文标题的分享图时，可用浏览器打开 `static/img/og-cover.svg` 截图导出 PNG，替换 `og-cover.png`
- [ ] Facebook Sharing Debugger / Twitter Card Validator 按需验证

### 3.5 上线后持续监控

- [ ] 每周看一次各站长平台的「索引覆盖率」与抓取异常
- [ ] 关注百度/GSC 的查询词数据，命中量高但排名 8-20 位的词优先做内容加深
- [ ] 每月更新一次指南类文章的时间戳（`data/seo/guides/*.json` 的 `date` 字段 + `SEO_LASTMOD`）

---

## 四、后续可继续做的（本次未做）

1. **扩展更多平台落地页**：复制 `data/seo/platforms/*.json` 即可，建议优先补充国内冷门但有搜索量的平台
2. **补充 FAQ 问答数据**：`data/seo/faq.json` 的 groups 里继续加，结构化数据会自动包含
3. **intro`/`caps` 内容加深**：落地页正文字数提升会直接影响长尾词排名
4. **图片 alt 与站点 universal avatar**：目前全站几乎无内容图片，后续加了图示再补 alt
5. **hreflang 多语言**：仅在真正做英文版之后再考虑，不要提前配置
