"""情感分析配置（全部由 .env 驱动）"""

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


# 是否启用情感分析
ENABLE_SENTIMENT = _bool("ENABLE_SENTIMENT", default=True)

# 分析方式: "llm" (使用 DeepSeek) 或 "rule" (规则匹配) 或 "both"
SENTIMENT_MODE = os.getenv("SENTIMENT_MODE", "rule")

# 情绪类别
EMOTION_LABELS = ["happy", "sad", "angry", "anxious", "calm", "excited", "neutral"]

# 中文情感关键词（规则匹配用）
POSITIVE_WORDS = [
    "开心", "高兴", "快乐", "喜欢", "爱", "好", "棒", "赞", "哈哈",
    "嘿嘿", "嘻嘻", "太好了", "nice", "good", "happy", "感谢", "谢谢",
    "兴奋", "激动", "期待", "满足", "幸福", "开心死了", "笑死", "绝了"
]
NEGATIVE_WORDS = [
    "难过", "伤心", "哭", "生气", "愤怒", "讨厌", "恨", "烦", "累",
    "焦虑", "紧张", "害怕", "担心", "失望", "无聊", "孤独", "痛苦",
    "崩溃", "无语", "呵呵", "算了", "随便", "唉", "哎", "郁闷"
]
