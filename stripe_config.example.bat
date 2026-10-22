@echo off
chcp 65001 >nul
rem ============================================================
rem  会员支付（Stripe）· 本地配置示例
rem  用法：复制本文件为 stripe_config.bat，填入真实密钥后双击启动。
rem  密钥只存在于本机环境变量，不会写入任何代码文件。
rem
rem  ⚠ 安全提示：本文件会被 git 跟踪，只能保留占位符。
rem    真实配置请写入 stripe_config.bat（已在 .gitignore 中）。
rem ============================================================

rem ---- 必填 1：Stripe 测试模式 Secret Key（sk_test_ 开头）----
rem 获取：https://dashboard.stripe.com/test/apikeys → 「Secret key」→ Reveal
rem 生产上线时换成「Live」模式的 sk_live_ 开头密钥
set STRIPE_SECRET_KEY=sk_test_替换为你的测试密钥

rem ---- 必填 2：Webhook 签名密钥（whsec_ 开头）----
rem 获取：终端执行（CLI 1.53+ 必须用 --events 显式指定事件）：
rem   stripe listen --forward-to 127.0.0.1:8899/api/stripe/webhook --events checkout.session.completed,checkout.session.expired,checkout.session.async_payment_succeeded,checkout.session.async_payment_failed
rem      启动后屏幕上打印的那一行 "Your webhook signing secret is whsec_xxx"
set STRIPE_WEBHOOK_SECRET=whsec_替换为你的签名密钥

rem ---- 必填 3：应用会话密钥（任意长随机串，用于加密登录 Cookie）----
rem 生成示例：openssl rand -hex 32  或随便打一段 32 位以上的乱码
set APP_SECRET_KEY=请替换为一段随机字符串

rem ---- 可选：Stripe 后台已创建的 Price ID（price_ 开头）----
rem 不填也能跑：程序会自动用下方 ONETIME_AMOUNT 临时创建价格并在页面展示。
rem 填了更规范：Dashboard → 产品 → 添加产品 → 一次性 → 价格 ¥100.00 CNY → 复制价格 ID
rem set STRIPE_PRICE_LIFETIME=price_替换为你的价格ID

rem ---- 可选：终身版定价（单位：分）与币种 ----
rem 必须与 Stripe 后台价格保持一致，否则发货前会触发金额校验拦截
rem set STRIPE_PRICE_LIFETIME_AMOUNT=10000
rem set STRIPE_PRICE_LIFETIME_CURRENCY=cny

rem ---- 可选：站点外网地址（默认取请求头，本地开发无需设置）----
rem set PUBLIC_BASE_URL=http://127.0.0.1:8899

rem ---- 可选：大模型配置（AI 总结能力）----
rem 环境变量只在本窗口生效：用本文件启动时，AI 总结需要这三个变量。
rem 把 llm_config.bat 里的对应 set 行复制到这里（去掉 rem），或直接粘进你本地的
rem stripe_config.bat 中 call run.bat 之前。
rem set LLM_API_KEY=sk-你的密钥
rem set LLM_BASE_URL=https://api.hcnsec.cn/v1
rem set LLM_MODEL=auto

echo.
echo [HJ] Stripe 支付已启用（测试模式）
echo [HJ] 正在启动服务…
echo.
call run.bat
