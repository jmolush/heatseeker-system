@echo off
echo Running Heatseeker Market Data Tests...
echo.

:: Activate venv if it exists
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

python test_market_data.py
pause
