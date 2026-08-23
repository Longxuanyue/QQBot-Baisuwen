"""对话管理配置（全部由 .env 驱动）"""

import os
from pathlib import Path


# ── 显式加载 .env，避免因插件导入顺序导致配置为空 ──
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=False)
except ImportError:
    pass


# 对话最大保留轮数（user+assistant 各算一轮）
DIALOG_MAX_TURNS = int(os.getenv("DIALOG_MAX_TURNS", "20"))

# 会话超时时间（秒），超过此时间无活动则自动清理
DIALOG_SESSION_TTL = int(os.getenv("DIALOG_SESSION_TTL", "1800"))  # 30 分钟

# 自动清理间隔（秒）
AUTO_CLEANUP_INTERVAL = int(os.getenv("AUTO_CLEANUP_INTERVAL", "600"))  # 10 分钟
