# 会员购买（Stripe 支付）设计文档

> 文档版本：v1.0 ｜ 最后修改：2026-10-22
> 范围：新增邮箱密码账号体系、Stripe 一次性买断（终身会员 ¥100）、权益发放与鉴权拦截。
> 运行环境：Windows / Python 3.13 / Flask 3.1 / SQLite（标准库）

---

## 一、需求背景与目标

项目已有视频下载解析与 AI 视频总结两大能力。此前定价页只是静态展示，按钮被 `app.js`
拦截成「支付通道开发中」提示。本次目标是把这条链路做成真实闭环：

1. 用户能注册 / 登录（邮箱 + 密码）；
2. 能在定价页下单，跳转 Stripe 托管收银台完成支付；
3. 支付成功后**自动**获得终身会员，AI 总结与字幕能力解锁；
4. 未登录 / 非会员访问 AI 总结时被明确拦截并引导升级；
5. **不能重复扣款**，同一事件重复到达也不能重复发货。

### 明确划定的边界

- **下载与解析永久免费**：`/api/info`、`/api/download`、`/api/status`、`/api/file`、`/api/playlist`
  契约零改动，不设任何鉴权。
- 只有三处加会员鉴权：`POST /api/summarize`、`GET /api/summary/subtitle/<id>`、`POST /api/summary/subtitle`。
- 采用**一次性买断**（¥100），不是订阅，因此不处理续费、取消、扣款失败重试等订阅态。

---

## 二、决策记录表

| # | 决策项 | 结论 | 理由 |
| --- | --- | --- | --- |
| D1 | 如何识别"会员是谁" | 自建邮箱 + 密码账号体系 | 用户确认；无需 SMTP / 短信，离线可跑 |
| D2 | 收费模式 | **一次性买断 ¥100**（终身会员） | 用户确认；无续费无取消，状态机最简单 |
| D3 | 权益范围 | 只限制 AI 总结与字幕下载 | 用户确认；下载解析保持免费，改动面最小 |
| D4 | 本地无公网如何联调 | **Stripe CLI 隧道转发** Webhook | 用户确认"能连 Stripe 但无公网地址" |
| D5 | 持久化选型 | SQLite（`data/hj.db`） | 标准库 `sqlite3`，零新增 pip 依赖 |
| D6 | Stripe 接入方式 | 官方 SDK `stripe>=12,<13` | 支付签名属安全边界，不自研 crypto |
| D7 | 密码哈希 | `werkzeug.security` | 已是 Flask 传递依赖，无需 bcrypt / argon2 |
| D8 | 支付页形态 | Stripe **托管 Checkout**（跳转） | 不接触卡数据，前端改动最小 |
| D9 | CSRF 防护 | 双提交 Token，覆盖 4 个改状态接口 | 其余接口强制 JSON，跨站表单本身需预检 |
| D10 | 是否做离线模拟支付 | **不做** | 用户环境可连 Stripe；双实现造成技术债 |
| D11 | 金额来源 | 服务端唯一常量表 `payments.PLANS` | 前端只传 `plan_code`，杜绝客户端改价 |

---

## 三、技术选型与版本核实（Context7）

| 项 | 结论 | 出处 |
| --- | --- | --- |
| 库标识 | Context7 ID：`/stripe/stripe-python` | Context7 resolve-library-id |
| 版本 | **v12.5.1**（2026-10-22 拉取，High 可信度） | Context7 返回的版本信息 |

关键 API 以官方文档为准，并在本地 `import stripe` 后逐个 `inspect.signature` 复验：

| 用途 | 官方写法 | 说明 |
| --- | --- | --- |
| 客户端初始化 | `stripe.StripeClient(api_key, max_network_retries=2)` | 版本留空则跟随账号默认 |
| 创建 Checkout | `client.checkout.sessions.create(params, options)` | `options` 支持 `idempotency_key` |
| 幂等键 | `{"idempotency_key": order_id}` | 显式指定可跨网络失败保证 exactly-once |
| 查询 Session | `client.checkout.sessions.retrieve(session_id, options)` | 成功页兜底同步用 |
| 验签 | `client.construct_event(payload, sig_header, secret)` | v8+ 推荐写法 |
| 验签容忍窗口 | `DEFAULT_TOLERANCE = 300` 秒 | 防重放攻击 |
| 验签失败异常 | `stripe.SignatureVerificationError` | 必须返回 400，不重试 |

---

## 四、数据模型

SQLite 四张表（`membership.init_db()` 幂等建表）：

```
users            id(PK) / email(UNIQUE) / password_hash / created_at
memberships      user_id(PK→users) / plan / status / source_order_id / source_session_id
                 granted_at / expires_at(NULL = 终身)
orders           id(PK) / user_id / plan / amount / currency / status
                 stripe_session_id(UNIQUE, 非空时) / stripe_payment_intent
                 checkout_url / created_at / paid_at
webhook_events   event_id(PK) / event_type / received_at
```

- `orders.stripe_session_id` 的唯一索引放在**数据库层**，是幂等的最后一道防线。
- 所有 SQL 一律参数化绑定，禁止字符串拼接。
- 连接策略：**每请求短连接** + `PRAGMA journal_mode=WAL` + `timeout=10`，
  避免 Flask 多线程下跨线程共享连接。

---

## 五、幂等性设计（核心）

用户明确要求"不能重复付款"。这里一共布了**四层去重**，任何一层单独失效都不致出问题：

```
点击购买
  ├─(第 1 层) 已存在 paid 订单 或 已是会员 ────► 409 already_member，拒绝
  ├─(第 1 层续) 存在 24h 内 pending 订单 ──────► 复用原 Checkout Session 链接
  └─ 新建订单(order_id = uuid4().hex)
        └─ Stripe: idempotency_key = client_reference_id = metadata.order_id = order_id
                   （第 2 层，Stripe 侧去重）

Webhook 到达
  ├─(第 3 层) INSERT OR IGNORE webhook_events(event_id) —— 冲突即跳过，返回 200
  ├─(第 4 层) UPDATE orders SET status='paid' WHERE id=? AND status='pending'
  │           影响行数 = 0 说明已发货，停止
  └─ INSERT OR IGNORE memberships(...) —— 重复开通也是幂等的
```

> 关键取舍：**发货的唯一触发源是验签通过的 Webhook**。
> `success_url` 只承担"展示 + 轮询"，即便用户手动伪造该 URL 也无法开通会员。

---

## 六、接口契约

### 6.1 账号

| 方法与路径 | 请求体 | 成功响应 | 失败响应 |
| --- | --- | --- | --- |
| `GET /account` | — | 登录注册页 HTML | — |
| `POST /api/auth/register` | `{email, password}` | `200 {ok, email, is_member}` | `400` / `403 csrf_failed` / `429` |
| `POST /api/auth/login` | `{email, password}` | `200 {ok, email, is_member}` | `400 {error:"邮箱或密码不正确"}` |
| `POST /api/auth/logout` | — | `200 {ok:true}` | — |
| `GET /api/me` | — | `{logged_in, email, display, is_member}` | — |

说明：登录成功后**轮换 session 与 CSRF Token**（防会话固定）；登录失败不区分
"邮箱不存在 / 密码错误"，并对不存在的邮箱也执行一次同等开销的哈希校验，防止账号枚举。

### 6.2 支付

| 方法与路径 | 请求体 | 成功响应 | 失败响应 |
| --- | --- | --- | --- |
| `POST /api/checkout` | `{plan:"lifetime"}` | `200 {order_id, checkout_url}` | `401` / `409 already_member` / `502` / `429` |
| `GET /api/order/<id>` | query `sync=1` 可选 | `200 {order_id, status, plan, amount, currency, paid, is_member}` | `401` / `404` |
| `POST /api/stripe/webhook` | Stripe 原始 body | `200 {received:true, granted:bool}` | `400` 验签失败 / `503` 未配置 |
| `GET /pay/success` | query `order` | 结果页 HTML | — |
| `GET /pay/cancel` | — | 结果页 HTML（取消态） | — |

### 6.3 会员鉴权错误契约（前端据此渲染升级卡片）

```json
{ "error": "此功能为终身会员专属", "code": "membership_required",
  "upgrade_url": "/pricing", "logged_in": true }
```

未登录时为 `"code": "login_required"`；HTTP 状态码分别为 **403**（非会员）与 **401**（未登录）。

### 6.4 契约零改动清单（回归安全带）

`/api/info`、`/api/download`、`/api/status/<job_id>`、`/api/file/<job_id>`、`/api/playlist`、
AI 总结的 SSE 事件格式与 `result` JSON 结构 —— **一律未改**。

---

## 七、环境变量

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `STRIPE_SECRET_KEY` | 是 | `sk_test_...`（测试）/ `sk_live_...`（生产） |
| `STRIPE_WEBHOOK_SECRET` | 是 | `whsec_...`，由 Stripe CLI 或 Dashboard 提供 |
| `APP_SECRET_KEY` | 建议 | Flask 会话签名密钥；未设置时随机生成（重启后需重新登录） |
| `STRIPE_PRICE_LIFETIME` | 否 | 后台创建的 Price ID；不填则用 `price_data` 内联生成 |
| `STRIPE_PRICE_LIFETIME_AMOUNT` | 否 | 单位「分」，默认 `10000`（¥100） |
| `STRIPE_PRICE_LIFETIME_CURRENCY` | 否 | 默认 `cny` |
| `PUBLIC_BASE_URL` | 否 | 站点外网地址，默认取请求 `host_url` |
| `MEMBERSHIP_DB` | 否 | SQLite 路径，默认 `data/hj.db` |

配置模板见 `stripe_config.example.bat`（复制为 `stripe_config.bat` 后填写，已在 `.gitignore`）。

---

## 八、安全性清单

1. **密钥只在环境变量**：启动日志只打印"已配置 / 未配置"，任何响应不回显密钥。
2. **Webhook 必须用原始字节体验签**：`request.get_data()`。绝不能 `get_json()` 后重新
   序列化 —— 键序与空格差异会让 HMAC 不匹配，这是新手最常踩的坑。
3. **验签失败返回 400**，日志只写"签名校验失败"，**不打印 payload**。
4. **处理异常返回 5xx** 触发 Stripe 重试；重试安全由幂等设计保证，不在失败路径做补偿发货。
5. **金额服务端决定**：客户端只传 `plan_code`；发货前再拿 `session.amount_total` 二次比对，
   不一致时**拒绝发货并告警**（防后台配错价导致多扣或被低价白嫖）。
6. **发货依据唯一**：成功页轮询的兜底同步必须先校验**订单归属当前登录用户**，否则会变成越权开通通道。
7. **会话安全**：`httponly=True`、`samesite=Lax`、`secure=False`（本地 http；上 HTTPS 后改为 True）。
8. **CSRF**：双提交 Token，覆盖注册 / 登录 / 登出 / 下单；登录成功即轮换 Token。
9. **限流**：注册 8 次/分、登录 10 次/分、下单 10 次/分（按 IP 或用户）。
10. **open redirect 防护**：跳转参数 `next` 只允许站内相对路径（`//evil.com` 会被拒绝）。
11. **`.gitignore` 已追加** `stripe_config.bat`、`data/*.db`、`data/*.db-wal`、`data/*.db-shm`。
    项目历史上发生过真实密钥随提交泄漏，提交前务必用 `git status --porcelain` 逐一核对。

---

## 九、文件变更清单

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `membership.py` | 新增 | SQLite 四表、注册/登录、密码哈希、会员判定、订单状态机、事件去重 |
| `payments.py` | 新增 | Stripe 客户端、Checkout 下单、验签、金额校验、`PLANS` 价源 |
| `app.py` | 修改 | 会话与 CSRF、鉴权装饰器、账号/下单/订单/Webhook 路由、3 处接口鉴权 |
| `templates/account.html` | 新增 | 登录注册页 |
| `templates/pay_success.html` | 新增 | 支付结果页（轮询三态） |
| `templates/nav_auth.html` | 新增 | 导航登录态桌面端片段 |
| `templates/nav_auth_mobile.html` | 新增 | 导航登录态移动端片段 |
| `templates/member_nav.html` | 新增 | 会员页共用导航栏 |
| `templates/member_footer.html` | 新增 | 会员页共用页脚与脚本引入 |
| `templates/pricing.html` | 修改 | 双档买断改版、真实下单按钮、FAQ 与页脚文案同步 |
| `templates/index.html` | 修改 | 导航登录态 + CSRF meta |
| `templates/summarize.html` | 修改 | 导航登录态、付费墙区块、引入 membership.js |
| `templates/seo/nav.html` | 修改 | SEO 页共用导航登录态 |
| `templates/en/pricing.html` | 修改 | 英文定价页同步买断价格 |
| `static/js/membership.js` | 新增 | 统一请求封装、登录注册、下单、结果轮询 |
| `static/js/app.js` | 修改 | 移除过期的 `data-coming-soon` 提示 |
| `static/js/summary.js` | 修改 | 401/403 渲染付费墙且不清空已输入 URL |
| `static/css/style.css` | 修改 | 追加账号/会员/支付/付费墙样式（复用既有变量） |
| `tests/test_membership.py` | 新增 | 49 条用例的自执行回归测试 |
| `requirements.txt` | 修改 | 新增 `stripe>=12,<13` |
| `.gitignore` | 修改 | 追加密钥与数据库忽略规则 |
| `stripe_config.example.bat` | 新增 | 环境变量占位模板 |
| `data/seo/site_profile.json` | 修改 | 收费说明同步 |

---

## 十、Stripe 上手指引（第一次做支付请照抄执行）

### 第 1 步：注册 Stripe 账号

1. 打开 https://dashboard.stripe.com/register ，用邮箱注册。
2. 完成邮箱验证。**个人开发者可以先不激活** —— 测试模式（`Test mode`）不需要开通收款资质。
3. 页面右上角务必确认处于 **「测试模式」**（开关显示为 Testing / 数据是测试数据）。
   测试模式下的钱都是假的，不会产生真实扣款。

### 第 2 步：拿到 Secret Key

1. 访问 https://dashboard.stripe.com/test/apikeys
2. 找到 **Secret key** 一行 → 点 `Reveal test key` → 复制（形如 `sk_test_51xxxxx`）。
3. 粘贴到 `stripe_config.bat`（从 `stripe_config.example.bat` 复制而来）的 `STRIPE_SECRET_KEY=`。

> ⚠ Secret key 等同于银行卡密码，**不要**提交到 git、不要贴到聊天记录、不要写进前端代码。
> 本项目已经把 `stripe_config.bat` 加进 `.gitignore`。

### 第 3 步（可选但推荐）：在后台创建产品与价格

1. Dashboard → 商品 → 产品目录 → **添加产品**
2. 名称填 `HJ 视频下载 · 终身会员`，描述随意。
3. 价格：**一次性付款**，金额 `100.00`，币种 **CNY（人民币）**。
4. 保存后点进该价格，复制右上角的 **价格 ID**（形如 `price_1xxxxx`）。
5. 填到 `stripe_config.bat` 的 `STRIPE_PRICE_LIFETIME=price_xxx`。

> 如果跳过这步也能跑：程序会用 `payments.PLANS` 里的金额自动生成一个内联价格。
> 但上线前建议补齐，方便在后台看报表和调价。

### 第 4 步：安装 Stripe CLI

Windows 推荐用 Scoop（没有 Scoop 就直接下载 exe）：

```powershell
scoop bucket add stripe https://github.com/stripe/scoop-stripe-cli.git
scoop install stripe
```

或者：到 https://github.com/stripe/stripe-cli/releases/latest 下载 `stripe_X.X.X_windows_x86_64.zip`，
解压后把 `stripe.exe` 所在目录加进 PATH。

验证安装：

```powershell
stripe --version
```

### 第 5 步：登录 CLI（一次性）

```powershell
stripe login --api-key sk_test_你的测试密钥
```

看到 `Done!` 即可。之后所有命令都不再需要重复登录。

### 第 6 步：启动本机 Webhook 隧道（每次联调都要开）

**保持这个窗口一直开着**，另开一个窗口启动网站：

```powershell
stripe listen --forward-to 127.0.0.1:8899/api/stripe/webhook --events checkout.session.completed,checkout.session.expired,checkout.session.async_payment_succeeded,checkout.session.async_payment_failed
```

> **注意**：Stripe CLI 1.53+ 起 `listen` 必须用 `--events` 显式指定要转发的事件，
> 否则会报错 `must specify events to forward using --events, --all-snapshot, or --all-thin`。
> 上面的清单与 `membership.SUPPORTED_EVENTS` 白名单一一对应；
> 不建议用 `--all-snapshot`（会转发大量无关事件刷屏）。
>
> 顺带验证 CLI 能否连上 Stripe（可选）：
>
> ```powershell
> stripe trigger checkout.session.completed
> ```

终端会打印一行：

```
Your webhook signing secret is whsec_xxxxxxxxxxxxxxxx
```

把这整串 `whsec_xxx` 填进 `stripe_config.bat` 的 `STRIPE_WEBHOOK_SECRET=`，然后重启网站。

> 原理：你的电脑是内网地址，Stripe 服务器无法主动访问 127.0.0.1。
> Stripe CLI 会在你的机器和 Stripe 之间拉一条加密隧道，把事件转发到本地。
> **不需要公网 IP、不需要域名、不需要 HTTPS。**

### 第 7 步：启动网站

```powershell
stripe_config.bat
```

（该脚本会设置好环境变量后调用 `run.bat`。如果还没改名，先 `copy stripe_config.example.bat stripe_config.bat`。）

看到日志出现「Stripe 支付已启用：终身会员 ¥100.00 CNY（测试密钥）」即成功。

### 第 8 步：跑一次真实测试支付

1. 浏览器打开 http://127.0.0.1:8899/pricing
2. 点「登录 / 注册」→ 注册一个邮箱（随便编，例如 `test@example.com`）
3. 回到定价页点「立即开通终身版」→ 自动跳转 Stripe 收银台
4. **卡号填 `4242 4242 4242 4242`**，有效期填任意未来月份（如 `12/34`），
   CVC 填任意三位（如 `123`），姓名邮编随意，邮箱填刚才注册的邮箱
5. 点 Pay → 回到 `/pay/success`
6. 页面显示「终身会员已开通」，导航栏出现金色「终身会员」徽章
7. 去 `/summarize` 粘贴视频链接，AI 总结功能已解锁

### 第 9 步：各种卡号场景验收表

| 卡号 | 场景 | 预期结果 |
| --- | --- | --- |
| `4242 4242 4242 4242` | 成功 | 会员开通，导航出现徽章 |
| `4000 0000 0000 0002` | 卡片被拒 | 收银台提示拒付，订单保持 pending |
| `4000 0025 0000 3155` | 需要 3DS 验证 | 收银台弹出验证框，点「完成」后同样开通 |
| `4000 0000 0000 9995` | 余额不足 | 支付失败，订单不发货 |
| 直接点收银台返回箭头 | 用户取消 | 落到 `/pay/cancel`，显示"你已取消支付，没有产生任何扣款" |

### 第 10 步：验证幂等（最重要）

```powershell
# 用 Stripe CLI 手动重放同一个事件三次，会员不应重复发放
stripe trigger checkout.session.completed
stripe trigger checkout.session.completed
```

网站日志应打印：

```
[HJ][stripe] checkout.session.completed order=xxx 首次发货=True
[HJ][stripe] checkout.session.completed order=xxx 首次发货=False
```

数据库中 `memberships` 表对该用户**永远只有一行**。

另外在浏览器里连点多次「立即开通终身版」，应始终跳向同一个收银台 URL，
不会产生第二笔订单与第二次扣款。

---

## 十一、实施要点（防返工清单）

1. **绝不要**把 `request.get_json()` 的结果重新 `json.dumps()` 去验签。
2. **绝不要**把「浏览器跳转到 success_url」当作发货依据。
3. **绝不要**在 Webhook 失败分支里补偿发货 —— 交给 Stripe 重试。
4. `app.js` 被 index / pricing / 各 SEO 页共用，新增绑定必须元素判空。
5. 新增样式只允许复用 `style.css` 既有变量，不要硬编码颜色。
6. 总结页付费墙出现时**不清空用户已输入的 URL**，开通回来可直接续用。
7. 改动任何 Stripe 相关代码前，先写明「这是面向谁的钱」，宁可不发货也不多发。
8. Windows 输出中文时注意 GBK 终端，跑测试建议先 `$env:PYTHONIOENCODING="utf-8"`。

---

## 十二、验证记录

### 12.1 自动化测试

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe tests\test_membership.py
```

结果：**49 通过 / 0 失败**。覆盖以下场景：

| 分组 | 场景 |
| --- | --- |
| 数据层 | 邮箱归一化、重复邮箱、弱密码、非法邮箱、错误密码 |
| CSRF | 缺 Token → 403；带正确 Token → 200；登录后 Token 轮换 |
| 登录态 | 登出后 /api/me 未登录；初始为免费版 |
| 下单幂等 | 重复点击返回同一订单且**只调用一次 Stripe** |
| 越权 | 他人订单 404；未登录 401 |
| Webhook | 错误签名 400 且不发货；缺签名头 400 |
| 金额异常 | 金额不匹配 → 返回 200 标记 `amount_mismatch` 且**拒不发货** |
| 发货幂等 | 首次发货 True；同事件重投 False；不同事件重发同订单 False；会员记录仅一行 |
| 重复购买 | 已付费再下单 → 409 |
| 鉴权 | 未登录 401 `login_required`；免费用户 403 `membership_required`；会员放行 200 |
| 页面 | `/`、`/pricing`、`/summarize`、`/account`、`/pay/success`、`/faq` 全部 200 |
| 脱敏 | 响应中不含 `sk_test` / `whsec` |

### 12.2 既有回归

```powershell
.venv\Scripts\python.exe tests\test_summary_extras.py
```

结果：**全部通过**，未影响既有 AI 总结能力。

### 12.3 真实支付验收（2026-10-22，用户实测通过）

用 Stripe 测试卡 `4242 4242 4242 4242` 走完真实链路，结果：

1. 收银台支付成功 → 回调 /pay/success → 页面显示「终身会员已开通」
2. 导航栏出现金色「终身会员」徽章，`/api/me` 返回 `is_member: true`
3. `/summarize` 的 AI 总结功能解锁

### 12.4 验收阶段发现并修复的问题

| # | 现象 | 根因 | 修复 |
| --- | --- | --- | --- |
| B1 | `stripe listen` 报 `must specify events to forward using --events, --all-snapshot, or --all-thin` | Stripe CLI 1.53+ 起不再默认转发全部事件 | 命令改为显式指定事件：`--events checkout.session.completed,checkout.session.expired,checkout.session.async_payment_succeeded,checkout.session.async_payment_failed`（与 `SUPPORTED_EVENTS` 一一对应）；README 与设计文档同步修正 |
| B2 | 支付成功页「一闪一闪」不停闪烁 | 轮询发现已支付后 `window.location.reload()` 刷新整页 → 刷新后重新进入待确认并再次轮询 → 再次 reload，形成循环 | `membership.js` 用 `sessionStorage` 按订单号标记，**只允许刷新一次**（刷新为更新导航栏徽章）；`sessionStorage` 不可用时干脆不刷新 |
| B3 | 配了大模型但仍提示「尚未配置大模型」 | 环境变量按窗口生效：`stripe_config.bat` 里没有 LLM 变量 | 把 `llm_config.bat` 的 4 行 `set LLM_*` 并入 `stripe_config.bat`（在 `call run.bat` 之前）；`stripe_config.example.bat` 模板补充该坑的说明 |
| B4 | 服务启动即崩：`UnicodeEncodeError: 'gbk' codec can't encode '\xa5'` | 启动日志里的 `¥` 字符；stdout 被重定向到文件/管道时 Python 回退 GBK 编码 | `app.py` 的 `__main__` 开头对 `sys.stdout/stderr` 执行 `reconfigure(encoding="utf-8", errors="replace")`。挂真实控制台（双击启动）因 PEP 528 不受影响，故此前未暴露 |

> 附带教训：判断「大模型是否已配置」不能 grep 页面源码——
> 总结页的「尚未配置大模型」引导卡片是常驻 HTML（默认 `hidden`），
> 由前端调 `/api/llm/config` 的 `configured` 字段显隐。要查接口而非源码文本。

### 12.5 HTTP 冒烟测试

实际启动 `app.py` 后逐页访问，状态码均为 200：

```
/                200    /pay/success    200
/pricing         200    /summarize      200
/account         200    /faq            200
/en/pricing      200
```

### 12.6 用户验收结论（2026-10-22 · 全部通过）

依赖真实环境的三项已由用户实测确认：

1. 测试卡 `4242 4242 4242 4242` 完成支付并自动开通会员 —— **通过**（见 12.3）；
2. 重复点击「立即开通终身版」始终复用同一收银台、不产生第二笔订单 —— **通过**；
3. `stripe trigger` 重放同一事件，`memberships` 不重复插入 —— **通过**。

至此会员购买功能闭环验收完成，代码已提交并推送至 GitHub（提交 `036bc3f`）。

---

## 十三、后续可选项（本期未做）

- **退款闭环**：处理 `charge.refunded` 回收会员（当前只预留 `mark_expired` / 订单状态）。
- **支付 SMTP 凭证**：支付成功后给邮箱发一封开通凭证（当前无 SMTP 依赖）。
- **Stripe Tax 自动计税**：跨境收款时按需开启 `automatic_tax`。
- **管理后台**：查看订单与手动开通会员（当前只能直接改 SQLite）。
- **生产部署**：需把 `SESSION_COOKIE_SECURE` 改为 True 并启用 HTTPS；
  上线前把 Dashboard 从 Test mode 切到 Live mode，替换 `sk_live_` 密钥，
  并到 Dashboard 重新配置正式版 Webhook 端点（此时不再需要 Stripe CLI 隧道）。