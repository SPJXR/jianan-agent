@echo off
rem 建安法规问答助手 一键启动（Windows）
rem 首次运行会自动创建虚拟环境、安装依赖并构建知识库索引
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
  echo [1/3] 首次运行：创建虚拟环境并安装依赖...
  uv venv .venv --python 3.14 || python -m venv .venv
  uv pip install --python .venv\Scripts\python.exe -r requirements.txt || .venv\Scripts\python.exe -m pip install -r requirements.txt
)

if not exist kb\kb.sqlite (
  echo [2/3] 构建知识库索引（解析 34 份文档，约 2-5 分钟）...
  .venv\Scripts\python.exe tools\extract_docs.py
  .venv\Scripts\python.exe tools\build_kb.py
)

echo [3/3] 启动服务：http://127.0.0.1:9000
start "" http://127.0.0.1:9000
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 9000
endlocal
