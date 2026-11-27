@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
if exist ".venv\Scripts\python.exe" goto environment_ready
set "SIGNUP_PYTHON="
python -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1
if not errorlevel 1 set "SIGNUP_PYTHON=python"
if defined SIGNUP_PYTHON goto create_environment
py -3 -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1
if not errorlevel 1 set "SIGNUP_PYTHON=py -3"
if defined SIGNUP_PYTHON goto create_environment
for %%P in ("D:\programs\miniconda3\python.exe" "%USERPROFILE%\miniconda3\python.exe" "%USERPROFILE%\anaconda3\python.exe" "%LOCALAPPDATA%\miniconda3\python.exe" "C:\ProgramData\miniconda3\python.exe" "C:\ProgramData\anaconda3\python.exe") do (
  if exist "%%~P" (
    "%%~P" -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1
    if not errorlevel 1 (
      set SIGNUP_PYTHON="%%~P"
      goto create_environment
    )
  )
)
echo 未检测到可用的 Python 3.10 或更新版本。
echo 请先安装 Python，安装时勾选 Add Python to PATH。
echo 下载地址：https://www.python.org/downloads/
echo 如果已安装 Anaconda，可先打开 Anaconda Prompt，进入本目录后运行 start.bat。
echo 安装完成后关闭本窗口，再次双击 start.bat。
pause
exit /b 1
:create_environment
%SIGNUP_PYTHON% -m venv .venv
if errorlevel 1 goto failed
:environment_ready
".venv\Scripts\python.exe" -c "import playwright, tzdata" >nul 2>&1
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto failed
)
if not exist ".venv\browser-ready" (
  ".venv\Scripts\python.exe" -m playwright install chromium
  if errorlevel 1 goto failed
  echo ready>".venv\browser-ready"
)
".venv\Scripts\python.exe" signup.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo 安装或运行失败，请保留上方完整报错信息。
pause
exit /b 1
