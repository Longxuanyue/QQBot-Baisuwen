"""
群聊学习插件配置（环境变量，风格与 nonebot_plugin_memory/config.py 一致）
"""

import os


def _bool(key: str, *, default: bool) -> bool:
    v = os.getenv(key, "")
    return v.lower() == "true" if v else default


def _int(key: str, default: int) -> int:
    v = os.getenv(key, "")
    return int(v) if v else default


# ── 总开关 ──
# 群聊学习总开关（默认关闭，逐群开启）
GROUP_LEARNING = _bool("GROUP_LEARNING", default=False)
# 新群默认是否开启学习（建议保持 False，由群主显式开启）
GROUP_LEARN_DEFAULT = _bool("GROUP_LEARN_DEFAULT", default=False)

# ── 数据 ──
# 群库目录（与用户记忆库同目录）
GROUP_USER_DATA_DIR = os.getenv("MEMORY_USER_DATA_DIR", "user_data")
# 群消息流水保留条数（超出后清理最旧消息）
GROUP_HISTORY_KEEP = _int("GROUP_HISTORY_KEEP", 500)

# ── LLM 批量任务 ──
# 群风格卡每日生成时刻（时:分）
GROUP_STYLE_CARD_TIME = os.getenv("GROUP_STYLE_CARD_TIME", "21:00")
# 或每累计多少条群消息触发一次风格卡（二者取先到）
GROUP_STYLE_CARD_INTERVAL = _int("GROUP_STYLE_CARD_INTERVAL", 500)
# 群记忆批量提取时刻（逗号分隔的 时:分 列表）
GROUP_MEMORY_EXTRACT_TIMES = os.getenv("GROUP_MEMORY_EXTRACT_TIMES", "12:30,20:30")
# 风格卡/群记忆提取专用模型（留空则用主对话模型）
GROUP_STYLE_MODEL = os.getenv("GROUP_STYLE_MODEL", "")

# ── 注入与行为 ──
# 群上下文块注入预算（token 估算值）
GROUP_CONTEXT_MAX_TOKENS = _int("GROUP_CONTEXT_MAX_TOKENS", 200)
# 注入的群记忆条数
GROUP_MEMORY_TOP_K = _int("GROUP_MEMORY_TOP_K", 3)
# 是否允许"氛围分"调节群回复概率（默认关闭；需 GROUP_REPLY_PROBABILITY > 0 才生效）
GROUP_ADAPTIVE_PROBABILITY = _bool("GROUP_ADAPTIVE_PROBABILITY", default=False)

# ── 内部参数（不建议修改） ──
# 消息流水批量写阈值（条）
GROUP_FLUSH_BATCH = 10
# 缓冲兜底刷新间隔（秒，APScheduler）
GROUP_FLUSH_INTERVAL = 30
# 氛围分：bot 回复后多少秒内有人接话视为正反馈
GROUP_ATMOSPHERE_WINDOW = 300.0
# 接话加分 / 无人接话衰减
GROUP_ATMOSPHERE_BOOST = 0.1
GROUP_ATMOSPHERE_DECAY = 0.05
# 氛围分上下限
GROUP_ATMOSPHERE_MIN = 0.2
GROUP_ATMOSPHERE_MAX = 1.5
# 昵称学习：同一昵称出现多少次才采纳
GROUP_NICKNAME_THRESHOLD = 3
