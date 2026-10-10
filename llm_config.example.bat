@echo off
chcp 65001 >nul
rem ============================================================
rem  AI 视频总结 · 大模型配置示例
rem  用法：复制本文件为 llm_config.bat，填入你的密钥后双击启动。
rem  密钥只存在于本机环境变量中，不会写入任何代码文件。
rem  默认平台：新疆幻城网安科技公益大模型安全网关 https://api.hcnsec.cn/
rem ============================================================

rem ---- 必填：你的 API Key（网关控制台「令牌」页面创建，sk- 开头）----
set LLM_API_KEY=sk-94yB1lRE7ZlYy8vmBsVAGUPBQDrmQ2feXSdjTcz7rzKl7KK8

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

echo.
echo [HJ] 已配置模型：%LLM_MODEL% @ %LLM_BASE_URL%
echo [HJ] 正在启动服务…
echo.
call run.bat
