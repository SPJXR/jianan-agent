@echo off
rem ============================================================
rem  Jianan Legal Q&A - one-click launcher (Windows)
rem  Chinese usage guide: see README (open it in any editor)
rem  This file must stay pure ASCII: cmd.exe parses it with the
rem  system OEM codepage, and chcp does NOT change that.
rem  v2 2026-10-19: port precheck; window stays open after server exit
rem ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "PORT=9000"
set "OUT=install_log.txt"
if exist "%OUT%" del "%OUT%" >nul 2>&1

echo [1/5] Creating virtualenv (skip if exists) ...
if exist .venv\Scripts\python.exe goto :venvready
where python >nul 2>&1
if not errorlevel 1 (
  python -m venv .venv
  if not errorlevel 1 goto :venvready
)
where py >nul 2>&1
if not errorlevel 1 (
  py -3 -m venv .venv
  if not errorlevel 1 goto :venvready
)
goto :nopython
:venvready
if not exist .venv\Scripts\python.exe goto :venvfail

echo [2/5] Virtualenv ready
rem ---- no version pre-check: parsing a version string in batch needs nested ----
rem ---- quotes, which cmd cannot do reliably. A too-old python fails at the ----
rem ---- pip / import step below, and that error is written to install_log.txt ----

echo [3/5] Installing dependencies (1-3 min, needs internet) ...
.venv\Scripts\python.exe -c "import fastapi,uvicorn,jieba,numpy,onnxruntime" >nul 2>&1
if not errorlevel 1 goto :depsok
if exist requirements.lock (
  .venv\Scripts\python.exe -m pip install -r requirements.lock >> "%OUT%" 2>&1
) else (
  .venv\Scripts\python.exe -m pip install -r requirements.txt >> "%OUT%" 2>&1
)
if errorlevel 1 goto :pipfail
:depsok
echo       dependencies OK >> "%OUT%"

echo [4/5] Checking knowledge index ...
if not exist kb\kb.sqlite (
  echo       building index, 2-5 min, needs MS Word installed ...
  .venv\Scripts\python.exe tools\extract_docs.py >> "%OUT%" 2>&1
  if errorlevel 1 goto :kbfail
  .venv\Scripts\python.exe tools\build_kb.py >> "%OUT%" 2>&1
  if errorlevel 1 goto :kbfail
)

echo [5/5] Checking TCP port %PORT% ...
netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul 2>&1
if not errorlevel 1 goto :portbusy

echo.
echo  STARTING  http://127.0.0.1:%PORT%
echo  Browser opens in about 6 seconds. If it shows "cannot reach this page",
echo  wait for the line "Uvicorn running on ..." below, then refresh.
echo  Keep this window open - it IS the server. Press CTRL+C to stop it.
echo.
start "" /b cmd /c "timeout /t 6 /nobreak >nul & start "" http://127.0.0.1:%PORT%"
rem ---- keep output on screen: the pass criterion is the "Uvicorn running" line. ----
rem ---- do NOT redirect it to the log, that would hide the reason from the user. ----
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%
set "SRVRC=%errorlevel%"
echo.
echo [EXIT] server process ended, exit code !SRVRC!
if "!SRVRC!"=="0" goto :end
echo        This window stays open so you can read the reason above.
echo        To send it back: right-click the title bar, click "Select All",
echo        press Enter - that copies everything, then paste it into a text file.
echo        pip install log: %CD%\%OUT%
echo        If it mentions a port, edit start.bat and set "PORT=9010".
pause
goto :end

:portbusy
echo [ERROR] TCP port %PORT% is already being listened on by another program.
echo         Fix: open start.bat in Notepad, change the line
echo             set "PORT=9000"
echo         to  set "PORT=9010"  and run again. The app will then be at
echo         http://127.0.0.1:9010
echo         If no program uses %PORT%, it may sit in a Windows reserved range -
echo         run the diagnostic script and send diag.txt back.
pause
goto :end

:nopython
echo [ERROR] Python not found on this machine.
echo         Install Python 3.11 or 3.14 from https://www.python.org/downloads/
echo         IMPORTANT: tick "Add python.exe to PATH" during install.
echo         Details: %OUT%
pause
goto :end

:badver
echo [ERROR] Python version is too old. This app needs Python 3.9 or newer.
echo         Install Python 3.11 or 3.14, then delete the .venv folder and run again.
pause
goto :end

:venvfail
echo [ERROR] Could not create the virtual environment.
echo         Send back the last lines of: %OUT%
pause
goto :end

:pipfail
echo [ERROR] Dependency install failed - usually a network or proxy issue.
echo         Retry with the Tsinghua mirror:
echo           .venv\Scripts\python.exe -m pip install -r requirements.lock ^
echo             -i https://pypi.tuna.tsinghua.edu.cn/simple
echo         Send back the last lines of: %OUT%
pause
goto :end

:kbfail
echo [ERROR] Knowledge index build failed.
echo         The package should already contain kb\kb.sqlite - re-extract the
echo         whole zip and try again. Details: %OUT%
pause
goto :end

:end
endlocal
