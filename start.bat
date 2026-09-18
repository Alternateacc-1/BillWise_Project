@echo off
REM ---------------------------------------------------------------
REM  BillSahi - start everything.
REM  Double-click this file, or run  start.bat  from a terminal.
REM ---------------------------------------------------------------
setlocal
set "ROOT=%~dp0"

echo Starting BillSahi...
echo.

REM --- API (port 8000) -------------------------------------------
start "BillSahi API" cmd /k ^
  ""%ROOT%venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --app-dir "%ROOT%backend""

REM --- UI (port 5173) --------------------------------------------
start "BillSahi UI" cmd /k ^
  "cd /d "%ROOT%frontend" && "E:\node.exe" node_modules\vite\bin\vite.js --port 5173 --host 127.0.0.1"

REM Give the servers a moment, then open the browser on the address
REM that actually works. Use 127.0.0.1, not localhost: the servers bind
REM to IPv4 only, and localhost can resolve to IPv6 ::1 and fail.
timeout /t 5 /nobreak >nul
start "" http://127.0.0.1:5173

echo.
echo   UI    http://127.0.0.1:5173
echo   API   http://127.0.0.1:8000
echo.
echo Two windows have opened - one per server. Close them to stop.
echo.
pause
