"""用户画像配置（全部由 .env 驱动）"""

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


def _bool(key: str, *, default: bool) -> bool:
    v = os.getenv(key, "")
    return v.lower() == "true" if v else default


# 是否启用用户画像
ENABLE_PROFILE = _bool("ENABLE_PROFILE", default=True)

# 画像更新间隔：每 N 条新记忆后更新一次
PROFILE_UPDATE_INTERVAL = int(os.getenv("PROFILE_UPDATE_INTERVAL", "100"))

# 画像缓存刷新间隔（秒）：超过后后台线程重建，不阻塞消息链路
PROFILE_REFRESH_SECONDS = int(os.getenv("PROFILE_REFRESH_SECONDS", "1800"))  # 30 分钟

# 画像摘要最大字数
PROFILE_MAX_WORDS = int(os.getenv("PROFILE_MAX_WORDS", "300"))
