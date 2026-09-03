@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PY="
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set "PY=%LocalAppData%\Programs\Python\Python311\python.exe"
if not defined PY if exist "%LocalAppData%\Programs\Python\Python310\python.exe" set "PY=%LocalAppData%\Programs\Python\Python310\python.exe"
if not defined PY (
  for /f "delims=" %%i in ('where python 2^>nul') do (
    echo %%i | findstr /i "WindowsApps" >nul
    if errorlevel 1 if not defined PY set "PY=%%i"
  )
)

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

if not defined PY (
    echo 找不到 Python 3。请安装 Python 并勾选 Add python.exe to PATH。
    echo 或把 python.exe 放到 %%LocalAppData%%\Programs\Python\Python3xx\
    pause
    exit /b 1
)

echo 使用: %PY%
"%PY%" "%~dp0app.py"
if errorlevel 1 (
    echo.
    echo 程序异常退出。日志：%%APPDATA%%\SplitNIC\error.log
    pause
)
