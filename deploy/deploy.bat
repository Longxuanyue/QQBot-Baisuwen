@echo off
setlocal
title 白苏文 (BaiSuWen) 一键部署

REM =====================================================
REM   白苏文 一键部署器 (Windows)
REM   用法：双击此文件
REM   功能：自动检测/安装 Python 3.10+，然后运行 deploy\deploy.py
REM   说明：Python 固定下载 3.12.10（3.12.11 起为仅源码的
REM         安全维护版，不再提供 Windows 安装包，请勿升级此版本号）
REM =====================================================

REM 切换到项目根目录（%~dp0 指向本脚本所在 deploy\ 目录）
cd /d "%~dp0.."

echo.
echo ============================================
echo     白苏文 (BaiSuWen) 一键部署器
echo ============================================
echo.

REM ---------- 检测 Python：py -3.12、py -3、python、python3 ----------

:try_py312
where py >nul 2>&1
if errorlevel 1 goto :try_py3
py -3.12 -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if errorlevel 1 goto :try_py3
set "PY_CMD=py"
set "PY_ARGS=-3.12"
goto :found_python

:try_py3
py -3 -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if errorlevel 1 goto :try_python
set "PY_CMD=py"
set "PY_ARGS=-3"
goto :found_python

:try_python
where python >nul 2>&1
if errorlevel 1 goto :try_python3
python -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if errorlevel 1 goto :try_python3
set "PY_CMD=python"
set "PY_ARGS="
goto :found_python

:try_python3
where python3 >nul 2>&1
if errorlevel 1 goto :install_python
python3 -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if errorlevel 1 goto :install_python
set "PY_CMD=python3"
set "PY_ARGS="
goto :found_python

REM ---------- 自动下载并安装 Python 3.12.10 ----------

:install_python
if defined REINSTALLED goto :manual_install
set "REINSTALLED=1"
echo [信息] 未检测到可用的 Python 3.10+，开始自动安装 Python 3.12.10 ...
echo        （安装包约 27 MB，若网络较慢请耐心等待）

set "PY_INSTALLER=%TEMP%\python-3.12.10-amd64.exe"

REM 下载源优先级：阿里云镜像 → 清华镜像 → 官方源
REM 三个源均需显式启用 TLS 1.2（PS 5.1 默认 TLS 1.0/1.1 会导致下载失败）
set "PY_URL_ALI=https://mirrors.aliyun.com/python/3.12.10/python-3.12.10-amd64.exe"
set "PY_URL_TUNA=https://mirrors.tuna.tsinghua.edu.cn/python/3.12.10/python-3.12.10-amd64.exe"
set "PY_URL_OFF=https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"

echo [信息] 正在下载 Python 安装包（镜像站优先，失败将自动切换源）...

:try_aliyun
del "%PY_INSTALLER%" >nul 2>&1
echo [信息] 尝试阿里云镜像下载...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%PY_URL_ALI%' -OutFile '%PY_INSTALLER%'"
if not exist "%PY_INSTALLER%" goto :try_tuna
for %%F in ("%PY_INSTALLER%") do if %%~zF LSS 10000000 goto :try_tuna
goto :download_ok

:try_tuna
del "%PY_INSTALLER%" >nul 2>&1
echo [信息] 尝试清华镜像下载...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%PY_URL_TUNA%' -OutFile '%PY_INSTALLER%'"
if not exist "%PY_INSTALLER%" goto :try_official
for %%F in ("%PY_INSTALLER%") do if %%~zF LSS 10000000 goto :try_official
goto :download_ok

:try_official
del "%PY_INSTALLER%" >nul 2>&1
echo [信息] 尝试官方源下载...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%PY_URL_OFF%' -OutFile '%PY_INSTALLER%'"
if not exist "%PY_INSTALLER%" goto :manual_install
for %%F in ("%PY_INSTALLER%") do if %%~zF LSS 10000000 goto :manual_install

:download_ok
echo [信息] 下载完成，正在静默安装（无需管理员权限）...
start /wait "" "%PY_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0 Include_pip=1
set "INSTALL_EXIT=%ERRORLEVEL%"
if "%INSTALL_EXIT%"=="3010" set "INSTALL_EXIT=0"
if not "%INSTALL_EXIT%"=="0" echo [警告] 安装程序返回码 %INSTALL_EXIT%，继续检测...

REM 当前 cmd 会话的 PATH 不含新安装的 Python，手工拼接
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    set "PY_ARGS="
    goto :found_python
)
goto :try_py312

REM ---------- 手动安装指引 ----------

:manual_install
echo.
echo [错误] 未能自动下载或安装 Python。
echo        请手动完成以下步骤后重新运行本脚本：
echo        1. 打开 https://www.python.org/downloads/
echo        2. 下载 Python 3.12 并安装，勾选 "Add python.exe to PATH"
echo        3. 安装完成后重新双击本脚本
start "" "https://www.python.org/downloads/"
pause
exit /b 1

REM ---------- 运行部署脚本 ----------

:found_python
echo.
echo [信息] 使用 Python: %PY_CMD% %PY_ARGS%
if not exist "deploy\deploy.py" (
    echo [错误] 未找到 deploy\deploy.py，请确认脚本所在位置正确。
    pause
    exit /b 1
)
echo.
"%PY_CMD%" %PY_ARGS% "deploy\deploy.py"
set "DEPLOY_EXIT=%ERRORLEVEL%"
echo.
if "%DEPLOY_EXIT%"=="0" (
    echo [完成] 部署脚本执行完毕。
) else (
    echo [错误] 部署脚本异常退出 (exit code: %DEPLOY_EXIT%)
)
pause
exit /b %DEPLOY_EXIT%
