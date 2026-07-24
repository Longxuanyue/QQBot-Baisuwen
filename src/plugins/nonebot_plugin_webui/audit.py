"""
审计日志：记录所有 WebUI 操作，支持查询
"""

import json
import os
import time
from typing import Optional

from nonebot import logger

from .config import AUDIT_LOG_FILE


def log_action(
    user_id: str,
    action: str,
    target: str = "",
    detail: str = "",
    ip: str = "",
) -> None:
    """
    记录一条审计日志（JSONL 格式，追加写入）。

    :param user_id: 操作者 QQ 号
    :param action: 操作类型 (login, config.save, plugin.toggle, memory.delete, bot.restart 等)
    :param target: 操作目标（如插件名、文件名）
    :param detail: 操作详情
    :param ip: 操作者 IP
    """
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "user": str(user_id),
        "action": action,
        "target": target,
        "detail": detail,
        "ip": ip,
    }

    os.makedirs(os.path.dirname(AUDIT_LOG_FILE), exist_ok=True)
    try:
        with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error(f"写入审计日志失败: {e}")


def query_logs(
    limit: int = 200,
    offset: int = 0,
    action_filter: str = "",
    user_filter: str = "",
    date_from: str = "",
    date_to: str = "",
) -> dict:
    """
    查询审计日志，支持筛选和分页。

    返回:
        {"total": int, "entries": list[dict], "limit": int, "offset": int}
    """
    if not os.path.exists(AUDIT_LOG_FILE):
        return {"total": 0, "entries": [], "limit": limit, "offset": offset}

    entries = []
    with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # 筛选
            if action_filter and entry.get("action", "") != action_filter:
                continue
            if user_filter and entry.get("user", "") != user_filter:
                continue
            ts = entry.get("ts", "")
            if date_from and ts < date_from:
                continue
            if date_to and ts > date_to:
                continue

            entries.append(entry)

    total = len(entries)
    # 倒序（最新的在前）
    entries.reverse()
    # 分页
    paged = entries[offset:offset + limit]

    return {
        "total": total,
        "entries": paged,
        "limit": limit,
        "offset": offset,
    }


# 启动记录
# 缓存最近一次启动时间，避免每次请求都扫描整个审计日志
_cached_startup_time: Optional[str] = None


def log_startup():
    """记录 Bot 启动事件"""
    global _cached_startup_time
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    _cached_startup_time = ts
    entry = {
        "ts": ts,
        "user": "system",
        "action": "bot.startup",
        "target": "",
        "detail": "Bot 启动",
        "ip": "",
    }
    os.makedirs(os.path.dirname(AUDIT_LOG_FILE), exist_ok=True)
    try:
        with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def get_last_startup_time() -> Optional[str]:
    """获取最近一次启动时间（优先使用缓存，缓存失效时回退扫描文件）"""
    global _cached_startup_time
    if _cached_startup_time:
        return _cached_startup_time
    # 回退：从审计日志中查找（仅在缓存未设置时使用）
    if not os.path.exists(AUDIT_LOG_FILE):
        return None
    last_ts = None
    with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("action") == "bot.startup":
                    last_ts = entry.get("ts")
            except json.JSONDecodeError:
                continue
    _cached_startup_time = last_ts
    return last_ts
