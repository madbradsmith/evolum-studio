@echo off
REM Evolum Studio - one-command start for Windows. Double-click this file.
cd /d "%~dp0"

echo.
echo   Evolum Studio - starting up
echo   ---------------------------
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo   Python is not installed.
  echo   Get it from https://www.python.org/downloads/
  echo   IMPORTANT: tick "Add Python to PATH" during install.
  echo.
  pause
  exit /b 1
)
echo   [1/4] Python found.

if not exist venv (
  echo   [2/4] Creating a private Python environment ^(first run only^)...
  python -m venv venv
) else (
  echo   [2/4] Environment already set up.
)
call venv\Scripts\activate.bat

echo   [3/4] Installing dependencies ^(first run takes a minute^)...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

if not exist .env (
  copy /y .env.example .env >nul
  python -c "import secrets,pathlib; p=pathlib.Path('.env'); t=p.read_text(); p.write_text(t.replace('SECRET_KEY=replace-with-a-long-random-string','SECRET_KEY='+secrets.token_urlsafe(48)))"
  echo   [4/4] Created .env with a fresh random SECRET_KEY.
) else (
  echo   [4/4] Using your existing .env
)

echo.
echo   Ready. Opening http://localhost:7000
echo   Press Ctrl+C in this window to stop.
echo.

start "" http://localhost:7000
python app.py
pause
