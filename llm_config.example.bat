@echo off
chcp 65001 >nul
rem ============================================================
rem  AI 视频总结 · 大模型配置示例
rem  用法：复制本文件为 llm_config.bat，填入你的密钥后双击启动。
rem  密钥只存在于本机环境变量中，不会写入任何代码文件。
rem  默认平台：新疆幻城网安科技公益大模型安全网关 https://api.hcnsec.cn/
rem ============================================================

rem ---- 必填：你的 API Key（网关控制台「令牌」页面创建，sk- 开头）----
rem 安全提示：本文件会被 git 跟踪，切勿写入真实密钥；本地配置请复制为 llm_config.bat（已在 .gitignore 中）
set LLM_API_KEY=sk-替换为你的密钥

rem ---- 接口地址（OpenAI 兼容）----
rem 幻城网安公益网关（默认）  https://api.hcnsec.cn/v1
rem DeepSeek 官方            https://api.deepseek.com
rem 智谱 GLM                 https://open.bigmodel.cn/api/paas/v4
rem 本地 Ollama              http://127.0.0.1:11434/v1
set LLM_BASE_URL=https://api.hcnsec.cn/v1

rem ---- 模型名 ----
rem auto = 网关智能路由，一定可用，适合先跑通
rem 想固定模型，请填网关控制台「模型广场」里的准确 ID，例如：
rem   deepseek-v3.2 / deepseek-v4-pro / glm-5.1 / qwen3.6-plus / kimi-k2.6
rem 查询可用 ID：启动后访问 http://127.0.0.1:8899/api/llm/models
set LLM_MODEL=auto

rem ---- 可选：单次请求超时（秒），长视频可调大 ----
set LLM_TIMEOUT=180

rem ---- 可选：网关偶发断连（RemoteDisconnected）时的自动重试 ----
rem 次数（默认 3）与退避基数秒数（默认 2，实际等待 2s/4s…）
rem set LLM_RETRY_ATTEMPTS=3
rem set LLM_RETRY_DELAY=2

rem ---- 可选：超长字幕分块阈值与并发（默认 60000 字符 / 3 并发）----
rem set SUMMARY_CHUNK_CHARS=60000
rem set SUMMARY_MAX_CONCURRENCY=3

echo.
echo [HJ] 已配置模型：%LLM_MODEL% @ %LLM_BASE_URL%
echo [HJ] 正在启动服务…
echo.
call run.bat
