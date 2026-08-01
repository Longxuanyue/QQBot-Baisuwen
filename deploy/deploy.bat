@echo off
chcp 65001 >nul 2>&1
title 白苏文 (BaiSuWen) 一键部署

REM =============================================
REM   白苏文 一键部署器 (Windows)
REM   用法：双击此文件
REM   说明：自动使用系统 Python 运行 deploy.py
REM =============================================

REM 切换到 deploy/ 所在目录的上级（项目根目录）
cd /d "%~dp0.."

echo.
echo ╔══════════════════════════════════════╗
echo ║   白苏文 一键部署器 (Windows)       ║
echo ╚══════════════════════════════════════╝
echo.

REM 查找 Python
set PYTHON_EXE=
for %%p in (python3 python py) do (
    where %%p >nul 2>&1
    if not errorlevel 1 (
        set PYTHON_EXE=%%p
        goto :found_python
    )
)

echo [错误] 未找到 Python，请先安装 Python 3.10+
echo        下载地址: https://www.python.org/downloads/
pause
exit /b 1

:found_python
echo [信息] 使用 Python: %PYTHON_EXE%

REM 执行部署脚本
"%PYTHON_EXE%" deploy\deploy.py
set DEPLOY_EXIT=%ERRORLEVEL%

echo.
if %DEPLOY_EXIT% equ 0 (
    echo [完成] 部署脚本执行完毕。
) else (
    echo [错误] 部署脚本异常退出 (exit code: %DEPLOY_EXIT%)
)

pause
