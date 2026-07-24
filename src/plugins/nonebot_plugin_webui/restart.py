"""
重启管理：信号文件 + 看门狗协议
"""

import os
import threading

from .config import DATA_DIR

RESTART_SIGNAL_FILE = os.path.join(DATA_DIR, ".restart_signal")


def request_restart() -> bool:
    """
    写入重启信号文件并返回 True。
    实际重启由外部看门狗脚本或用户手动执行。
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(RESTART_SIGNAL_FILE, "w") as f:
            f.write("1")
        return True
    except Exception:
        return False


def clear_restart_signal():
    """清除重启信号（启动时调用）"""
    if os.path.exists(RESTART_SIGNAL_FILE):
        os.remove(RESTART_SIGNAL_FILE)


def is_restart_pending() -> bool:
    """检查是否有待处理的重启"""
    return os.path.exists(RESTART_SIGNAL_FILE)


def schedule_restart_exit(delay: float = 3.0):
    """
    在独立线程中延迟退出进程（exit code 42）。

    延迟是为了让 HTTP 响应先发送完成。
    退出码 42 是看门狗脚本约定的"请求重启"信号，
    看门狗检测到 42 后会重新拉起 Bot 进程。

    注意：必须使用 os._exit() 而非 sys.exit()，
    因为 sys.exit() 在非主线程中只退出当前线程，不会终止进程。
    """
    def _exit():
        import time
        time.sleep(delay)
        # os._exit() 立即终止整个进程，不执行清理（finally/__exit__/atexit）
        # 这是有意为之：HTTP 响应已发送，只需让看门狗检测到 exit 42 并重启
        os._exit(42)

    t = threading.Thread(target=_exit, daemon=True)
    t.start()


def get_restart_script() -> str:
    """生成启动脚本内容（Windows .bat）"""
    return '''@echo off
chcp 65001 >nul
title 白苏文 Bot - 看门狗

REM =============================================
REM  白苏文 Bot 启动看门狗脚本
REM  用法：双击运行此文件，或命令行执行
REM  功能：Bot 进程退出后自动重启
REM  退出码 42 = WebUI 请求重启 → 自动重启
REM  其他退出码 = 正常退出 → 停止看门狗
REM =============================================

REM 配置：虚拟环境路径（相对于本脚本所在目录）
set VENV_PATH=..\\nonebot\\Scripts\\activate.bat

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
echo   %%date%% %%time%%
echo   项目目录: %%cd%%
echo ========================================
echo.

nb run
set EXIT_CODE=%%ERRORLEVEL%%

echo.
echo ----------------------------------------
echo   Bot 已退出 (exit code: %%EXIT_CODE%%)
echo   %%date%% %%time%%
echo ----------------------------------------
echo.

REM 退出码 42 = WebUI 触发的重启请求
if %%EXIT_CODE%% equ 42 (
    echo   [看门狗] 检测到 WebUI 重启请求，3秒后自动重启...
    timeout /t 3 /nobreak >nul
    goto loop
)

REM 其他退出码 = 不再自动重启
echo   [看门狗] Bot 已正常退出，看门狗停止。
echo   按任意键关闭此窗口...
pause >nul
'''
