@echo off
REM Start DAC Minutes Studio on one URL: http://localhost:8000
REM First run creates the Python environment and installs packages.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating the Python environment ^(first run only^) ...
  python -m venv .venv || goto :error
  .venv\Scripts\python.exe -m pip install --upgrade pip >nul
  .venv\Scripts\python.exe -m pip install -r requirements.txt || goto :error
)

REM The archive ships the compiled interface (frontend\dist), so Node.js is only
REM needed when it is missing or when you ask for a rebuild.
if not exist "frontend\dist\index.html" (
  where npm >nul 2>nul || (
    echo.
    echo The interface is not built and Node.js is not installed.
    echo Install Node.js 18+ from https://nodejs.org and run this file again.
    pause
    exit /b 1
  )
  if not exist "frontend\node_modules" (
    echo Installing frontend packages ^(first run only^) ...
    pushd frontend
    call npm ci --no-audit --no-fund || call npm install --no-audit --no-fund || (popd & goto :error)
    popd
  )
  echo Building the interface ...
  pushd frontend
  call npm run build || (popd & goto :error)
  popd
)

echo.
echo   DAC Minutes Studio  -^>  http://localhost:8000
echo   Sign-in codes appear in this window until a mail server is configured.
echo.
".venv\Scripts\python.exe" app.py
goto :eof

:error
echo.
echo Setup failed. Check that Python 3.10+ and Node.js 18+ are installed and on PATH.
pause
