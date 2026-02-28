@echo off
echo Starting Heatseeker Backend Server...
echo.

:: Activate venv if it exists
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

python server.py
pause
