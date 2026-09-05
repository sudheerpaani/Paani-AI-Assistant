@echo off
cd /d "%~dp0"
if exist "paani_env\Scripts\python.exe" (
    set PYTHON_CMD=paani_env\Scripts\python.exe
) else (
    set PYTHON_CMD=python
)
start "" /B %PYTHON_CMD% server.py
start "" /B %PYTHON_CMD% tray_app.py
