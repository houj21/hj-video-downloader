@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [HJ] 首次运行：正在创建 Python 3.13 虚拟环境...
  py -3.13 -m venv .venv
  if errorlevel 1 (
    echo [HJ] 未找到 Python 3.13，请先安装：https://www.python.org/downloads/
    pause
    exit /b 1
  )
  echo [HJ] 正在安装依赖（使用清华镜像加速）...
  ".venv\Scripts\python.exe" -m pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
)

echo [HJ] 服务启动中，浏览器访问: http://127.0.0.1:8899
".venv\Scripts\python.exe" app.py
pause
