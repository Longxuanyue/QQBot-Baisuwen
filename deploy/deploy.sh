#!/usr/bin/env bash
# =============================================
#   白苏文 一键部署器 (Linux / macOS)
#   用法: bash deploy/deploy.sh
# =============================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   白苏文 一键部署器 (Linux/macOS)   ║"
echo "╚══════════════════════════════════════╝"
echo ""

# 查找 Python 3.10+
PYTHON_EXE=""
for p in python3.12 python3.11 python3.10 python3; do
    if command -v "$p" &>/dev/null; then
        PY_VER=$("$p" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        MAJOR=$("$p" -c "import sys; print(sys.version_info.major)")
        MINOR=$("$p" -c "import sys; print(sys.version_info.minor)")
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 10 ]; then
            PYTHON_EXE="$p"
            break
        fi
    fi
done

if [ -z "$PYTHON_EXE" ]; then
    echo "[错误] 未找到 Python 3.10+，请先安装。"
    echo "       Ubuntu: sudo apt install python3.12 python3.12-venv"
    echo "       macOS:  brew install python@3.12"
    exit 1
fi

echo "[信息] 使用 Python: $PYTHON_EXE ($("$PYTHON_EXE" --version))"

# 执行部署脚本
"$PYTHON_EXE" deploy/deploy.py
echo ""
exit 0
