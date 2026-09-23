@echo off
REM Run School Management app locally (Windows)
cd /d "%~dp0"

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo Installing dependencies...
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo.
echo Starting server at http://127.0.0.1:5000
echo Login: admin@school.com / support
echo Press CTRL+C to stop.
echo.

python app.py
pause
