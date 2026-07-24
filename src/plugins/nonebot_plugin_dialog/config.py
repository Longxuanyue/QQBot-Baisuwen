"""对话管理配置"""

# 对话最大保留轮数（user+assistant 各算一轮）
DIALOG_MAX_TURNS = 20

# 会话超时时间（秒），超过此时间无活动则自动清理
DIALOG_SESSION_TTL = 1800  # 30 分钟

# 自动清理间隔（秒）
AUTO_CLEANUP_INTERVAL = 600  # 10 分钟
