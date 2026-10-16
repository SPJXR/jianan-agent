@echo off
rem JianAn QA Assistant - DEMO MODE (degraded, no LLM key)
rem Purpose: recording demo video shot 7 (degraded retrieval mode).
rem Forces LLM_API_KEY empty so .env key is NOT applied and the app enters retrieval-only fallback mode.
setlocal
chcp 65001 >nul
cd /d "%~dp0"

rem ---- force degraded mode: LLM_DISABLED=1 makes llm_configured() False ----
rem (Windows cmd cannot create an empty-but-present env var, so an explicit
rem  disable switch in app/config.py is used instead of clearing LLM_API_KEY)
set "LLM_DISABLED=1"

echo ============================================
echo   DEGRADED DEMO MODE (no LLM configured)
echo   URL : http://127.0.0.1:9101
echo   Check: /api/health should show "llmConfigured": false
echo   Q and A will return verbatim retrieval chunks only.
echo   Close this window to stop the demo instance.
echo ============================================

if not exist .venv\Scripts\python.exe (
  echo [1/2] First run: creating venv and installing deps...
  uv venv .venv --python 3.14 || python -m venv .venv
  uv pip install --python .venv\Scripts\python.exe -r requirements.txt || .venv\Scripts\python.exe -m pip install -r requirements.txt
)

if not exist kb\kb.sqlite (
  echo [2/2] Building knowledge base index, takes 2-5 min...
  .venv\Scripts\python.exe tools\extract_docs.py
  .venv\Scripts\python.exe tools\build_kb.py
)

echo Starting degraded demo instance on port 9101 ...
start "" http://127.0.0.1:9101
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 9101
endlocal
