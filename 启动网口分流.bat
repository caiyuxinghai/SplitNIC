@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PY="
if exist "%LocalAppData%\Programs\Python\Python312\pythonw.exe" set "PY=%LocalAppData%\Programs\Python\Python312\pythonw.exe"
if not defined PY if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%LocalAppData%\Programs\Python\Python311\pythonw.exe" set "PY=%LocalAppData%\Programs\Python\Python311\pythonw.exe"
if not defined PY if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set "PY=%LocalAppData%\Programs\Python\Python311\python.exe"
if not defined PY if exist "%LocalAppData%\Programs\Python\Python310\pythonw.exe" set "PY=%LocalAppData%\Programs\Python\Python310\pythonw.exe"
if not defined PY if exist "%LocalAppData%\Programs\Python\Python310\python.exe" set "PY=%LocalAppData%\Programs\Python\Python310\python.exe"
if not defined PY (
  for /f "delims=" %%i in ('where pythonw 2^>nul') do (
    echo %%i | findstr /i "WindowsApps" >nul
    if errorlevel 1 if not defined PY set "PY=%%i"
  )
)
if not defined PY (
  for /f "delims=" %%i in ('where python 2^>nul') do (
    echo %%i | findstr /i "WindowsApps" >nul
    if errorlevel 1 if not defined PY set "PY=%%i"
  )
)

if not defined PY (
    echo 找不到 Python 3。请安装 Python 并勾选 Add python.exe to PATH。
    echo 或把 python.exe 放到 %%LocalAppData%%\Programs\Python\Python3xx\
    pause
    exit /b 1
)

REM Do not auto-elevate. An elevated GUI cannot accept Explorer drag-drop (red blocked cursor).
start "" "%PY%" "%~dp0app.py"
exit /b 0
