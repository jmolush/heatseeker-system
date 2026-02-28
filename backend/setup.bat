@echo off
echo ============================================
echo  Heatseeker Trading System — Windows Setup
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.8+ from python.org
    echo Make sure "Add Python to PATH" is checked during install.
    pause
    exit /b 1
)

echo [1/4] Creating virtual environment...
python -m venv venv
if errorlevel 1 (
    echo ERROR: Failed to create virtual environment.
    pause
    exit /b 1
)

echo [2/4] Activating virtual environment...
call venv\Scripts\activate.bat

echo [3/4] Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo [4/4] Creating .env from template...
if not exist .env (
    copy .env.example .env
    echo Created .env — edit it with your settings before running.
) else (
    echo .env already exists — skipping.
)

echo.
echo ============================================
echo  Setup complete!
echo ============================================
echo.
echo Next steps:
echo   1. Edit .env with your capture path and API keys
echo   2. Start OpenD on this machine
echo   3. Run: python server.py
echo   4. Load the Chrome extension (chrome://extensions, Developer mode, Load unpacked)
echo.
pause
