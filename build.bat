@echo off
REM Build NetLessChat.exe (one file, no Python needed on the target PC)
REM Needs internet once to install PyInstaller.

if not exist venv (
    python -m venv venv
)
call venv\Scripts\activate
pip install --quiet pyinstaller
pyinstaller --onefile --console --clean --name NetLessChat --icon assets\icon.ico --add-data "web;web" main.py
echo.
echo Done! Your app is at: dist\NetLessChat.exe
pause
