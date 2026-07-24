"""
认证模块：Token 管理、Session 签名、角色权限
"""

import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Optional

from nonebot import logger

from .config import SECRET_KEY, TOKEN_TTL, SESSION_MAX_AGE, WEBUI_USERS_FILE


# ── Token 存储（内存） ──

class TokenStore:
    """登录 Token 管理（一次性，5分钟过期）"""

    def __init__(self):
        self._tokens: dict[str, dict] = {}

    def create(self) -> str:
        """生成新 Token，返回 token 字符串"""
        token = secrets.token_hex(16)
        now = time.time()
        self._tokens[token] = {
            "created_at": now,
            "expires_at": now + TOKEN_TTL,
            "verified": False,
            "used": False,
            "user_id": None,
        }
        # 清理过期 token
        self._cleanup()
        return token

    def verify(self, token: str, user_id: str) -> bool:
        """验证 Token：QQ 用户发来 /auth <token>"""
        entry = self._tokens.get(token)
        if entry is None:
            return False
        if entry["used"]:
            return False
        if time.time() > entry["expires_at"]:
            return False
        entry["verified"] = True
        entry["user_id"] = user_id
        return True

    def check(self, token: str) -> Optional[dict]:
        """轮询检查 Token 是否已被验证，验证成功后标记为已使用并返回用户信息"""
        entry = self._tokens.get(token)
        if entry is None:
            return None
        if time.time() > entry["expires_at"]:
            return None
        if entry["verified"] and not entry["used"]:
            entry["used"] = True  # 一次性使用
            return {"user_id": entry["user_id"]}
        return None

    def _cleanup(self):
        """清理过期 token"""
        now = time.time()
        expired = [t for t, e in self._tokens.items() if e["expires_at"] < now]
        for t in expired:
            del self._tokens[t]


token_store = TokenStore()


# ── Session 签名 ──

def _sign(data: str) -> str:
    """HMAC-SHA256 签名"""
    mac = hmac.new(SECRET_KEY.encode(), data.encode(), hashlib.sha256)
    return mac.hexdigest()


def create_session(user_id: str) -> str:
    """创建签名 Session Cookie 值"""
    payload = json.dumps({
        "user_id": user_id,
        "created_at": int(time.time()),
    })
    encoded = _b64_encode(payload)
    sig = _sign(encoded)
    return f"{encoded}.{sig}"


def verify_session(cookie_value: str) -> Optional[str]:
    """验证 Session Cookie，返回 user_id 或 None"""
    try:
        encoded, sig = cookie_value.rsplit(".", 1)
    except ValueError:
        return None

    if not hmac.compare_digest(_sign(encoded), sig):
        return None

    try:
        payload = json.loads(_b64_decode(encoded))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    # 检查过期
    if time.time() - payload.get("created_at", 0) > SESSION_MAX_AGE:
        return None

    return payload.get("user_id")


def _b64_encode(s: str) -> str:
    """URL-safe base64 编码"""
    import base64
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def _b64_decode(s: str) -> str:
    """URL-safe base64 解码"""
    import base64
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s).decode()


# ── 角色管理 ──

class Role:
    SUPER = "super"
    ADMIN = "admin"
    USER = "user"


# 权限矩阵：哪些角色可以访问哪些操作
_ROLE_PERMISSIONS = {
    Role.SUPER: {
        "dashboard.view", "dashboard.full",
        "plugins.view", "plugins.toggle",
        "config.view", "config.edit",
        "personality.view", "personality.edit",
        "memory.view", "memory.delete", "memory.clear",
        "audit.view",
        "backup.download", "backup.restore",
        "bot.restart",
        "users.manage",
    },
    Role.ADMIN: {
        "dashboard.view", "dashboard.full",
        "plugins.view", "plugins.toggle",
        "config.view",
        "personality.view",
        "memory.view",
        "backup.download",
    },
    Role.USER: {
        "dashboard.view",
    },
}


def get_user_role(user_id: str) -> str:
    """获取用户角色"""
    # SUPERUSERS 从环境变量读取
    superusers = _parse_superusers()
    if user_id in superusers:
        return Role.SUPER

    # 从用户角色文件读取
    users = _load_users_file()
    for role in [Role.ADMIN, Role.USER]:
        if user_id in users.get(role, []):
            return role

    return ""  # 无角色


def check_permission(user_id: str, action: str) -> bool:
    """检查用户是否有权限执行某操作"""
    role = get_user_role(user_id)
    if not role:
        return False
    return action in _ROLE_PERMISSIONS.get(role, set())


def get_role_permissions(role: str) -> set[str]:
    """获取角色的所有权限"""
    return _ROLE_PERMISSIONS.get(role, set())


def _parse_superusers() -> set[str]:
    """解析 SUPERUSERS 环境变量"""
    raw = os.getenv("SUPERUSERS", "[]")
    try:
        users = json.loads(raw)
        return {str(u) for u in users}
    except (json.JSONDecodeError, TypeError):
        return set()


def _load_users_file() -> dict:
    """加载用户角色文件"""
    if not os.path.exists(WEBUI_USERS_FILE):
        return {"super": [], "admin": [], "user": []}
    try:
        with open(WEBUI_USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"super": [], "admin": [], "user": []}


def save_users_file(data: dict) -> bool:
    """保存用户角色文件"""
    os.makedirs(os.path.dirname(WEBUI_USERS_FILE), exist_ok=True)
    try:
        with open(WEBUI_USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"保存用户角色文件失败: {e}")
        return False
