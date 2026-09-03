@echo off
chcp 65001 >nul
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
where python >nul 2>&1
if %errorlevel%==0 (
    python "%~dp0app.py"
    goto :eof
)
py -3 "%~dp0app.py"
