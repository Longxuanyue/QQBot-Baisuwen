import os
from pathlib import Path

# 基础目录（用于单用户模式默认路径）
BASE_DIR = Path(__file__).parent.parent

# 单用户模式数据库路径（兼容旧版）
SHORT_TERM_DB = os.getenv("MEMORY_SHORT_TERM_DB", str(BASE_DIR / "short_term.db"))
LONG_TERM_DB = os.getenv("MEMORY_LONG_TERM_DB", str(BASE_DIR / "long_term.db"))

# 多用户数据目录
USER_DATA_DIR = os.getenv("MEMORY_USER_DATA_DIR", "user_data")

# 容量上限
SHORT_TERM_MAX = int(os.getenv("MEMORY_SHORT_TERM_MAX", "2000"))
LONG_TERM_MAX = int(os.getenv("MEMORY_LONG_TERM_MAX", "5000"))

# 遗忘算法参数
BETA = float(os.getenv("MEMORY_BETA", "0.5"))
ETA = float(os.getenv("MEMORY_ETA", "0.3"))
WEIGHT_THRESHOLD = float(os.getenv("MEMORY_WEIGHT_THRESHOLD", "0.1"))

# 记忆管理参数
UPGRADE_IMPORTANCE_THRESHOLD = float(os.getenv("MEMORY_UPGRADE_IMPORTANCE_THRESHOLD", "0.7"))
UPGRADE_ACCESS_COUNT_THRESHOLD = int(os.getenv("MEMORY_UPGRADE_ACCESS_COUNT_THRESHOLD", "5"))
UPGRADE_WEIGHT_THRESHOLD = float(os.getenv("MEMORY_UPGRADE_WEIGHT_THRESHOLD", "0.5"))
SIMILARITY_THRESHOLD = float(os.getenv("MEMORY_SIMILARITY_THRESHOLD", "0.85"))
MERGE_SIMILARITY_THRESHOLD = float(os.getenv("MEMORY_MERGE_SIMILARITY_THRESHOLD", "0.9"))

# 冲突检测关键词（暂时不支持从环境变量配置复杂列表，保持代码内默认）
NEGATION_PATTERNS = [
    r"不(喜欢|爱|想要|需要|希望|愿意|是|会|能)",
    r"讨厌", r"厌恶", r"不再", r"已经不是", r"现在不",
    r"改(变|成|为)", r"换成", r"搬到", r"不再喜欢",
    r"以前.*现在", r"其实", r"实际上"
]
CHANGE_KEYWORDS = ["改成", "变为", "换成", "搬到", "更新为", "现在是", "其实", "实际上"]

# 记忆生成
DEFAULT_IMPORTANCE = float(os.getenv("MEMORY_DEFAULT_IMPORTANCE", "0.6"))
# 高重要性关键词列表（可考虑从环境变量JSON解析，暂不实现）
HIGH_IMPORTANCE_KEYWORDS = [
    "我是", "我叫", "我的名字是", "我住在", "我是医生", "我是一名",
    "我喜欢", "我讨厌", "我最爱", "我擅长", "我不会", "我不能", "我需要"
]

CONTEXT_HISTORY_LEN = int(os.getenv("MEMORY_CONTEXT_HISTORY_LEN", "2"))