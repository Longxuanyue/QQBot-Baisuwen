"""
WebUI 插件配置
"""

import os
import secrets

# WebUI 路由前缀
WEBUI_PREFIX = "/webui"

# Session 签名密钥（服务启动时自动生成，重启后所有 session 失效）
SECRET_KEY = os.getenv("WEBUI_SECRET_KEY", secrets.token_hex(32))

# Session 有效期（秒）
SESSION_MAX_AGE = 86400  # 24 小时

# 登录 Token 有效期（秒）
TOKEN_TTL = 300  # 5 分钟

# 数据存储目录（相对于项目根目录）
DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "data"
)

# 插件开关状态文件
PLUGIN_STATES_FILE = os.path.join(DATA_DIR, "webui_plugin_states.json")

# 审计日志文件
AUDIT_LOG_FILE = os.path.join(DATA_DIR, "webui_audit.jsonl")

# WebUI 用户角色文件
WEBUI_USERS_FILE = os.path.join(DATA_DIR, "webui_users.json")

# .env 备份目录
ENV_BACKUP_DIR = os.path.join(DATA_DIR, "env_backups")

# 记忆浏览分页大小
MEMORY_PAGE_SIZE = 50
