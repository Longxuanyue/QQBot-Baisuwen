"""多模态配置（全部由 .env 驱动，默认值与旧行为一致）"""

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


# 是否启用图片理解（LLM Vision）。
# 分析使用 LLM_VISION_MODEL（deepseek-v4-flash-vision-exp），
# 图片描述文本会注入对话上下文，由主对话模型（deepseek-v4-flash）继续回复。
# 需与 update_baisuwen 的 ENABLE_MULTIMODAL 同时开启。
ENABLE_VISION = _bool("ENABLE_VISION", default=True)

# 是否启用表情包识别
ENABLE_STICKER_RECOGNITION = _bool("ENABLE_STICKER_RECOGNITION", default=False)

# 图片缓存目录
IMAGE_CACHE_DIR = os.getenv("IMAGE_CACHE_DIR", "image_cache")
