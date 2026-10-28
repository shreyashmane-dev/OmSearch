@echo off
setlocal

title OM Search Engine - Launcher

echo ================================================================================
echo                     OM SEARCH ENGINE — APPLICATION LAUNCHER
echo ================================================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [!] Virtual environment not found. Running setup first...
    call setup.bat
    if %errorlevel% neq 0 exit /b %errorlevel%
)

echo [1/2] Starting FastAPI Backend on http://127.0.0.1:8000 ...
start "OM Search - Backend (FastAPI)" cmd /k "cd backend && ..\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000 --reload"

echo [2/2] Starting React Frontend on http://127.0.0.1:5173 ...
start "OM Search - Frontend (Vite)" cmd /k "cd frontend && npm run dev"

timeout /t 3 >nul

echo.
echo ================================================================================
echo [✓] OM Search is now running!
echo     - Frontend Search UI:  http://127.0.0.1:5173
echo     - Backend API Docs:    http://127.0.0.1:8000/docs
echo ================================================================================
echo.

start http://127.0.0.1:5173
pause
