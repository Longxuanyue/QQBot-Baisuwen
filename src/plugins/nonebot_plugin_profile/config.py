"""用户画像配置"""

# 是否启用用户画像
ENABLE_PROFILE = True

# 画像更新间隔：每 N 条新记忆后更新一次
PROFILE_UPDATE_INTERVAL = 100

# 画像缓存刷新间隔（秒）：超过后后台线程重建，不阻塞消息链路
PROFILE_REFRESH_SECONDS = 1800  # 30 分钟

# 画像摘要最大字数
PROFILE_MAX_WORDS = 300
