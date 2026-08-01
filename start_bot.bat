@echo off
title 白苏文 Bot - 看门狗

REM =============================================
REM   白苏文 Bot 启动看门狗脚本
REM   用法：双击运行此文件
REM   功能：Bot 进程退出后自动重启
REM   退出码 42 = WebUI 请求重启 - 自动重启
REM   其他退出码 = 正常退出 - 停止看门狗
REM =============================================

REM 配置：虚拟环境路径（相对于本脚本所在目录）
set VENV_PATH=..\nonebot\Scripts\activate.bat

REM 切换到脚本所在目录
cd /d "%~dp0"

REM 激活虚拟环境
if exist "%VENV_PATH%" (
    echo [看门狗] 激活虚拟环境: %VENV_PATH%
    call "%VENV_PATH%"
) else (
    echo [看门狗] 警告: 未找到虚拟环境 %VENV_PATH%，使用系统 Python
)

:loop
echo.
echo ========================================
echo   白苏文 Bot 启动中...
echo   %date% %time%
echo   项目目录: %cd%
echo ========================================
echo.

nb run
set EXIT_CODE=%ERRORLEVEL%

echo.
echo ----------------------------------------
echo   Bot 已退出 (exit code: %EXIT_CODE%)
echo   %date% %time%
echo ----------------------------------------
echo.

REM 退出码 42 = WebUI 触发的重启请求
if %EXIT_CODE% equ 42 (
    echo   [看门狗] 检测到 WebUI 重启请求，3秒后自动重启...
    timeout /t 3 /nobreak >nul
    goto loop
)

REM 其他退出码 = 不再自动重启
echo   [看门狗] Bot 已正常退出，看门狗停止。
echo   按任意键关闭此窗口...
pause >nul
