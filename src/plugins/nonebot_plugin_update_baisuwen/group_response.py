"""
按群响应控制 —— 对每个 QQ 群单独控制 bot 是否响应消息。

存储：user_data/group_response.json
{
  "default_enabled": true,      # 新群/未显式设置群的默认响应状态
  "groups": { "123456": true }  # 显式设置过的群（未列出的群跟随默认值）
}

读路径带内存缓存（TTL 10 秒），避免热路径频繁读盘；
写路径加线程锁 + 原子替换，写后立即更新缓存。
"""

import json
import os
import threading
import time

from nonebot import logger

from .config import PROJECT_ROOT, plugin_config

# ── 常量 ──

_PATH = os.path.join(PROJECT_ROOT, "user_data", "group_response.json")
_CACHE_TTL = 10.0  # 秒：读缓存有效期（外部手动改文件后最多 10 秒生效）

_lock = threading.Lock()

# 内存缓存：{"ts": 最后刷新时间, "default_enabled": bool, "groups": {gid: bool}}
_cache: dict = {"ts": 0.0, "default_enabled": True, "groups": {}}


# ── 内部读写 ──

def _load() -> dict:
    """读取存储文件；不存在或损坏时返回默认结构（不落盘）。"""
    default = {
        "default_enabled": plugin_config.group_response_default,
        "groups": {},
    }
    if not os.path.exists(_PATH):
        return default
    try:
        with open(_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"群响应开关配置读取失败: {e}")
        return default
    if not isinstance(data, dict):
        return default
    data.setdefault("default_enabled", plugin_config.group_response_default)
    data.setdefault("groups", {})
    return data


def _save(data: dict) -> None:
    """原子写入存储文件。"""
    os.makedirs(os.path.dirname(_PATH), exist_ok=True)
    tmp = _PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _PATH)


def _refresh_cache() -> None:
    """TTL 过期时从磁盘刷新缓存（带锁）。"""
    now = time.time()
    if now - _cache["ts"] < _CACHE_TTL:
        return
    with _lock:
        if now - _cache["ts"] < _CACHE_TTL:
            return
        data = _load()
        _cache["ts"] = now
        _cache["default_enabled"] = bool(
            data.get("default_enabled", plugin_config.group_response_default)
        )
        _cache["groups"] = dict(data.get("groups", {}))


def _invalidate_cache() -> None:
    """写操作后强制下一次读取重新加载磁盘。"""
    with _lock:
        _cache["ts"] = 0.0


# ── 对外查询 ──

def get_default_enabled() -> bool:
    """全局默认响应状态（未显式设置的群跟随）。"""
    _refresh_cache()
    return bool(_cache["default_enabled"])


def is_group_enabled(group_id: int) -> bool:
    """群是否响应消息。显式设置过的群按设置值，否则跟随全局默认。"""
    gid = str(group_id)
    _refresh_cache()
    groups = _cache.get("groups") or {}
    if gid in groups:
        return bool(groups[gid])
    return bool(_cache["default_enabled"])


# ── 对外修改 ──

def set_group_enabled(group_id: int, enabled: bool) -> None:
    """设置群响应开关（显式记录）。"""
    with _lock:
        data = _load()
        data.setdefault("groups", {})
        data["groups"][str(group_id)] = bool(enabled)
        _save(data)
    _invalidate_cache()
    logger.info(f"群 {group_id} 响应开关已设置为: {'开' if enabled else '关'}")


def reset_group(group_id: int) -> None:
    """移除群的显式设置，恢复跟随全局默认。"""
    with _lock:
        data = _load()
        data.setdefault("groups", {})
        data["groups"].pop(str(group_id), None)
        _save(data)
    _invalidate_cache()
    logger.info(f"群 {group_id} 已恢复跟随全局默认响应")


def set_default_enabled(enabled: bool) -> None:
    """设置全局默认响应状态（运行时生效，不写入 .env）。"""
    with _lock:
        data = _load()
        data["default_enabled"] = bool(enabled)
        _save(data)
    _invalidate_cache()
    logger.info(f"全局默认响应已设置为: {'开' if enabled else '关'}")


def list_group_states() -> dict:
    """返回所有显式设置过的群及其响应状态。"""
    _refresh_cache()
    return dict(_cache.get("groups") or {})
