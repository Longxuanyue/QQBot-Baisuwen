#!/usr/bin/env python3
"""
白苏文 (BaiSuWen) 一键部署脚本
===============================

从 GitHub 克隆仓库后，运行此脚本即可完成环境搭建和配置引导。

用法:
    python deploy/deploy.py            # 交互式部署
    python deploy/deploy.py --help     # 查看选项
"""

import os
import re
import sys
import shutil
import subprocess
import venv
from pathlib import Path


# ─────────────────────────── 终端颜色 ───────────────────────────

def _supports_color() -> bool:
    """检测终端是否支持 ANSI 颜色"""
    if os.name == "nt":
        return True  # Windows Terminal / PowerShell 支持
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"


def _c(code: str, text: str) -> str:
    """给文字包裹颜色代码"""
    if not _supports_color():
        return text
    return f"{code}{text}{RESET}"


def info(msg: str) -> None:
    print(f"{_c(BLUE, '[ 信息 ]')} {msg}")


def ok(msg: str) -> None:
    print(f"{_c(GREEN, '[ 成功 ]')} {msg}")


def warn(msg: str) -> None:
    print(f"{_c(YELLOW, '[ 警告 ]')} {msg}")


def error(msg: str) -> None:
    print(f"{_c(RED, '[ 错误 ]')} {msg}")


def step(n: int, total: int, msg: str) -> None:
    print(f"\n{_c(CYAN, f'━━━ 步骤 {n}/{total}: {msg} ━━━')}")


def ask(msg: str, default: str = "") -> str:
    """询问用户输入"""
    prompt = f"{_c(CYAN, '[ 输入 ]')} {msg}"
    if default:
        prompt += f" [{default}]"
    prompt += ": "
    result = input(prompt).strip()
    return result if result else default


def ask_yes_no(msg: str, default: bool = True) -> bool:
    """询问是/否"""
    hint = "Y/n" if default else "y/N"
    answer = ask(f"{msg} ({hint})", "")
    if not answer:
        return default
    return answer.lower() in ("y", "yes", "是")


# ─────────────────────────── 环境检测 ───────────────────────────

def check_python() -> tuple[str, tuple[int, int]]:
    """检测 Python 版本，返回 (可执行文件路径, (主版本, 次版本))"""
    exe = sys.executable
    major, minor = sys.version_info[:2]

    if (major, minor) < (3, 10):
        print()
        error(f"当前 Python 版本: {major}.{minor}")
        error("白苏文需要 Python >= 3.10，请升级后重试。")
        error("下载地址: https://www.python.org/downloads/")
        sys.exit(1)

    info(f"Python {major}.{minor} — {exe}")
    return exe, (major, minor)


def check_pip() -> str:
    """检测 pip 可用性"""
    try:
        import pip
        return str(pip.__version__)
    except ImportError:
        error("未检测到 pip，请先安装 pip 或使用包含 pip 的 Python 发行版。")
        sys.exit(1)


def check_git() -> bool:
    """检测 git 是否可用"""
    return shutil.which("git") is not None


# ─────────────────────────── 路径计算 ───────────────────────────

def get_project_root() -> Path:
    """获取项目根目录 (baisuwen/)"""
    return Path(__file__).resolve().parent.parent


def get_venv_path(root: Path) -> Path:
    """获取虚拟环境路径 (与 baisuwen 同级的 nonebot/)"""
    return root.parent / "nonebot"


def get_python_in_venv(venv_dir: Path) -> str:
    """获取虚拟环境中的 Python 可执行文件路径"""
    if os.name == "nt":
        return str(venv_dir / "Scripts" / "python.exe")
    else:
        return str(venv_dir / "bin" / "python3")


def get_pip_in_venv(venv_dir: Path) -> str:
    """获取虚拟环境中的 pip 路径"""
    if os.name == "nt":
        return str(venv_dir / "Scripts" / "pip.exe")
    else:
        return str(venv_dir / "bin" / "pip")


# ─────────────────────────── 创建虚拟环境 ───────────────────────────

def create_venv(venv_dir: Path, python_exe: str) -> None:
    """创建 Python 虚拟环境"""
    if venv_dir.exists():
        if not ask_yes_no(f"虚拟环境已存在 ({venv_dir})，是否重新创建？", default=False):
            info("保留现有虚拟环境")
            return
        info(f"删除现有虚拟环境: {venv_dir}")
        shutil.rmtree(venv_dir, ignore_errors=True)

    info(f"创建虚拟环境: {venv_dir}")
    builder = venv.EnvBuilder(
        with_pip=True,
        upgrade_deps=False,
        clear=True,
    )
    builder.create(str(venv_dir))
    ok("虚拟环境创建完成")


# ─────────────────────────── 安装依赖 ───────────────────────────

def run_pip(venv_dir: Path, args: list[str], desc: str = "") -> bool:
    """在虚拟环境中运行 pip"""
    pip = get_pip_in_venv(venv_dir)
    cmd = [pip] + args

    if desc:
        info(desc)

    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=False,
            cwd=str(get_project_root()),
        )
        return result.returncode == 0
    except Exception as exc:
        error(f"pip 执行异常: {exc}")
        return False


def install_dependencies(venv_dir: Path) -> None:
    """安装项目依赖"""
    root = get_project_root()

    # 升级 pip 和 setuptools
    run_pip(venv_dir, ["install", "--upgrade", "pip", "setuptools", "wheel"],
            "升级 pip / setuptools / wheel")

    # 安装 nb-cli（NoneBot 命令行工具）
    run_pip(venv_dir, ["install", "nb-cli>=0.7.0"],
            "安装 nb-cli (NoneBot CLI)")

    # 从 requirements.txt 安装所有依赖
    req_file = root / "requirements.txt"
    if req_file.exists():
        run_pip(venv_dir, ["install", "-r", str(req_file)],
                "安装 requirements.txt 依赖（含 PyTorch/Whisper，约 5~10 分钟）")
    else:
        warn("未找到 requirements.txt，将使用 pyproject.toml 安装")
        run_pip(venv_dir, ["install", "-e", str(root)],
                "安装 pyproject.toml 依赖")

    ok("依赖安装完成")


# ─────────────────────────── 配置文件 ───────────────────────────

def configure_env(root: Path) -> None:
    """引导用户配置 .env 文件"""
    env_path = root / ".env"
    example_path = root / ".env.example"

    # 检查是否已存在 .env
    if env_path.exists():
        if not ask_yes_no(".env 配置文件已存在，是否重新配置？", default=False):
            info("保留现有 .env 配置")
            return

    # 从模板复制
    if example_path.exists():
        shutil.copy(example_path, env_path)
        info(f"从 {example_path.name} 创建 .env 模板")
    else:
        warn("未找到 .env.example，将创建空白 .env")
        env_path.touch()

    # 读取现有内容
    content = env_path.read_text(encoding="utf-8")

    print()
    print(_c(BOLD, "══════════════════════════════════════"))
    print(_c(BOLD, "  配置引导 — 请填写以下必填项"))
    print(_c(BOLD, "══════════════════════════════════════"))
    print()
    print(_c(DIM, "（直接回车使用默认值/保持现状，Ctrl+C 可随时退出）"))
    print()

    # ── 必填项 ──
    deepseek_key = ask("DeepSeek API Key (必填，从 https://platform.deepseek.com/api_keys 获取)")
    if deepseek_key:
        content = _set_env(content, "DEEPSEEK_API_KEY", deepseek_key)

    superusers = ask("超级用户 QQ 号 (必填)", "2461292801")
    if superusers:
        # 确保 JSON 数组格式
        if not superusers.startswith("["):
            superusers = f'["{superusers}"]'
        content = _set_env(content, "SUPERUSERS", superusers)

    bot_nickname = ask("机器人昵称", "小玖")
    if bot_nickname:
        content = _set_env(content, "BOT_NICKNAME", bot_nickname)
        content = _set_env(content, "NICKNAME", f'["{bot_nickname}"]')

    # ── TTS 引擎 ──
    print()
    print(_c(CYAN, "TTS 语音引擎选择:"))
    print("  1. vits       — 默认 VITS 引擎（内嵌，无需额外配置）")
    print("  2. gpt_sovits — GPT-SoVITS 引擎（需额外下载模型和参考音频）")
    tts_choice = ask("请选择 [1/2]", "1")
    if tts_choice == "2":
        content = _set_env(content, "TTS_ENGINE", "gpt_sovits")
        gpt_version = ask("GPT-SoVITS 模型版本 (v1/v2/v3/v4/v2Pro/v2ProPlus)", "v2ProPlus")
        content = _set_env(content, "GPT_SOVITS_VERSION", gpt_version)
        gpt_path = ask("GPT-SoVITS 安装路径", "D:/GPT-SoVITS-main")
        content = _set_env(content, "GPT_SOVITS_CONFIG", f"{gpt_path}/GPT_SoVITS/configs/tts_infer.yaml")
        gpt_char = ask("默认角色名", "陈千语")
        content = _set_env(content, "GPT_SOVITS_DEFAULT_CHARACTER", gpt_char)
    else:
        content = _set_env(content, "TTS_ENGINE", "vits")

    # ── ASR ──
    print()
    enable_asr = ask_yes_no("启用语音识别 (ASR/Whisper)？", default=True)
    content = _set_env(content, "ENABLE_ASR", "true" if enable_asr else "false")
    if enable_asr:
        asr_size = ask("ASR 模型大小 (tiny/base/small/medium/large)", "small")
        content = _set_env(content, "ASR_MODEL_SIZE", asr_size)

    # ── 多模态 ──
    print()
    enable_multimodal = ask_yes_no("启用多模态图片理解？", default=True)
    content = _set_env(content, "ENABLE_MULTIMODAL", "true" if enable_multimodal else "false")

    # 写入
    env_path.write_text(content, encoding="utf-8")
    ok(f".env 配置已保存: {env_path}")
    print()
    print(_c(DIM, "提示：后续可手动编辑 .env 文件调整更多高级参数"))
    print(_c(DIM, "      完整参数说明见 deploy/README_DEPLOY.md"))


def _set_env(content: str, key: str, value: str) -> str:
    """在 .env 内容中设置或替换指定键的值"""
    pattern = re.compile(rf"^{key}\s*=\s*.*$", re.MULTILINE)
    new_line = f"{key}={value}"
    if pattern.search(content):
        return pattern.sub(new_line, content)
    else:
        # 追加到末尾
        if not content.endswith("\n"):
            content += "\n"
        return content + new_line + "\n"


# ─────────────────────────── 目录初始化 ───────────────────────────

def init_directories(root: Path) -> None:
    """初始化必要的运行时目录"""
    dirs = [
        "user_data",
        "data",
        "data/env_backups",
        "image_cache",
        "output",
    ]
    for d in dirs:
        path = root / d
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            info(f"创建目录: {d}/")

    ok("运行时目录已就绪")


# ─────────────────────────── 启动脚本 ───────────────────────────

def create_launcher(root: Path, venv_dir: Path) -> None:
    """确保 Windows 启动脚本存在并路径正确"""
    bat_path = root / "start_bot.bat"

    if bat_path.exists():
        info("start_bot.bat 已存在，跳过")
        return

    # 如果不存在，生成一个
    rel_activate = os.path.relpath(
        str(venv_dir / "Scripts" / "activate.bat"),
        str(root),
    )
    bat_content = f"""@echo off
title 白苏文 Bot - 看门狗

REM =============================================
REM   白苏文 Bot 自动重启看门狗脚本
REM   用法：双击此文件
REM   功能：Bot 异常退出时自动重启
REM   退出码 42 = WebUI 请求重启 - 自动重启
REM   其他退出码 = 彻底退出 - 停止看门狗
REM =============================================

REM 配置：虚拟环境路径（相对于本脚本所在目录）
set VENV_PATH={rel_activate}

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

REM 退出码 42 = WebUI 请求重启，自动重启
if %EXIT_CODE% equ 42 (
    echo   [看门狗] 检测到 WebUI 重启请求，3秒后自动重启...
    timeout /t 3 /nobreak >nul
    goto loop
)

REM 其他退出码 = 不自动重启
echo   [看门狗] Bot 彻底退出，看门狗停止。
echo   按任意键关闭此窗口...
pause >nul
"""
    bat_path.write_text(bat_content, encoding="gbk", errors="ignore")
    ok("start_bot.bat 已生成")


# ─────────────────────────── 主流程 ───────────────────────────

def main() -> None:
    """部署主流程"""
    print()
    print(_c(BOLD + GREEN, "╔══════════════════════════════════════╗"))
    print(_c(BOLD + GREEN, "║   白苏文 (BaiSuWen) 一键部署工具    ║"))
    print(_c(BOLD + GREEN, "╚══════════════════════════════════════╝"))
    print()
    info("本工具将引导你完成白苏文 Bot 的环境搭建和配置。")
    info("如有问题，请查看 deploy/README_DEPLOY.md")
    print()

    TOTAL_STEPS = 5

    # ── 步骤 1: 环境检测 ──
    step(1, TOTAL_STEPS, "检测 Python 运行环境")
    python_exe, _ = check_python()
    check_pip()

    # ── 步骤 2: 路径准备 ──
    step(2, TOTAL_STEPS, "准备虚拟环境路径")
    root = get_project_root()
    venv_dir = get_venv_path(root)
    info(f"项目根目录: {root}")
    info(f"虚拟环境路径: {venv_dir}")

    # ── 步骤 3: 创建虚拟环境 ──
    step(3, TOTAL_STEPS, "创建 Python 虚拟环境")
    create_venv(venv_dir, python_exe)

    # ── 步骤 4: 安装依赖 ──
    step(4, TOTAL_STEPS, "安装项目依赖（耗时较长，请耐心等待）")
    install_dependencies(venv_dir)

    # ── 步骤 5: 配置引导 ──
    step(5, TOTAL_STEPS, "配置 Bot 参数")
    configure_env(root)
    init_directories(root)
    create_launcher(root, venv_dir)

    # ── 完成 ──
    print()
    print(_c(BOLD + GREEN, "╔══════════════════════════════════════╗"))
    print(_c(BOLD + GREEN, "║         🎉 部署完成！                ║"))
    print(_c(BOLD + GREEN, "╚══════════════════════════════════════╝"))
    print()
    print(_c(BOLD, "启动白苏文 Bot:"))
    print(f"  方式一（推荐）: 双击 {_c(CYAN, 'start_bot.bat')}")
    print(f"  方式二（手动）: cd /d {root}")
    print(f"                   {get_python_in_venv(venv_dir)} -m nb_cli run")
    print()
    print(_c(BOLD, "前置条件（启动前请确保）:"))
    print("  1. DeepSeek API Key 已在 .env 中配置")
    print("  2. QQ 协议端已就绪（NapCat / Lagrange / LLOneBot）")
    print("  3. 协议端正连 WebSocket → ws://127.0.0.1:42200/onebot/v11/ws")
    print()
    print(_c(BOLD, "Web 管理后台:"))
    print("  启动后访问: http://127.0.0.1:42200/webui/")
    print(f"  使用 /auth 命令完成 QQ 侧登录验证")
    print()
    print(_c(DIM, "详细说明见 deploy/README_DEPLOY.md"))
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        warn("部署已取消")
        sys.exit(0)
    except Exception as exc:
        print()
        error(f"部署异常: {exc}")
        sys.exit(1)
