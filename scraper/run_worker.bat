@echo off
REM =================================================================
REM  Meesho Seller Central — local worker launcher (Windows)
REM =================================================================
REM  Starts the debug-mode Chrome (if not running) then launches worker.py.
REM  Place this file, along with worker.py / product_review.py / labels.py,
REM  in a folder such as C:\meesho-worker\
REM
REM  Install:
REM    1) Edit the paths below to match your system (CHROME_PATH, WORK_DIR).
REM    2) Run run_worker.bat once manually to verify it works.
REM    3) To auto-start on laptop boot, import the Task Scheduler XML
REM       (meesho_worker_task.xml) via: Task Scheduler > Import Task.
REM =================================================================

set CHROME_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"
set CHROME_PROFILE=C:\meesho_profile
set WORK_DIR=C:\meesho-worker
set DEBUG_PORT=9222

REM --- Optional: export Mongo connection (falls back to worker.py default)
REM set MESHO_MONGO_URI=mongodb://43.205.229.129:27017/
REM set MESHO_DB_NAME=meesho

echo [meesho-worker] Checking if debug Chrome is already running on port %DEBUG_PORT%...
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:%DEBUG_PORT%/json/version' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if %ERRORLEVEL% EQU 0 (
    echo [meesho-worker] Chrome already listening on %DEBUG_PORT% — reusing.
) else (
    echo [meesho-worker] Launching Chrome with remote debugging...
    start "" %CHROME_PATH% --remote-debugging-port=%DEBUG_PORT% --user-data-dir=%CHROME_PROFILE%
    REM wait a few seconds for Chrome to come up
    timeout /t 8 /nobreak > NUL
)

cd /d %WORK_DIR%
echo [meesho-worker] Starting worker loop...
python worker.py

echo [meesho-worker] Worker exited. Press any key to close.
pause > NUL
