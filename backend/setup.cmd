@echo off
setlocal
cd /d "%~dp0"
echo Creating venv if missing...
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv 2>nul
  if errorlevel 1 python -m venv .venv
)
echo Upgrading pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
echo Installing requirements...
".venv\Scripts\pip.exe" install -r requirements.txt
if errorlevel 1 (
  echo Install failed.
  exit /b 1
)
echo.
echo OK. Start server:
echo   .venv\Scripts\uvicorn.exe app.main:app --reload --host 127.0.0.1 --port 8000
endlocal
