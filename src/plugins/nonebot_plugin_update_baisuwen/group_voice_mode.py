"""
按群语音回复模式 —— 群聊回复方式（语音/文字）逐群独立控制。

与私聊（voice_mode.py，按用户存储）**互相隔离**：
私聊的 /voicemode 不影响任何群，本模块的 /群语音 也不影响任何用户私聊。

支持三种模式（与私聊一致的三元组）：
- auto:   语音进→语音出，文字进→文字出（默认）
- always: 该群总是语音回复
- text:   该群总是文字回复

存储：user_data/group_voice_mode.json
{
  "default_mode": "auto",             # 新群/未显式设置群的默认模式
  "groups": { "123456": "always" }    # 显式设置过的群
}

读写策略与 group_response.py 相同：读路径带内存缓存（TTL 10 秒），
写路径加线程锁 + 原子替换，写后立即刷新缓存。
"""

import json
import os
import threading
import time

from nonebot import logger

from .config import PROJECT_ROOT, plugin_config

# ── 常量 ──

_PATH = os.path.join(PROJECT_ROOT, "user_data", "group_voice_mode.json")
_CACHE_TTL = 10.0  # 秒：读缓存有效期（外部手动改文件后最多 10 秒生效）

# 内部模式名（与 voice_mode.py 的 VOICE_MODES 保持一致）
VOICE_MODES = ("auto", "always", "text")

_lock = threading.Lock()

# 内存缓存：{"ts": 最后刷新时间, "default_mode": str, "groups": {gid: mode}}
_cache: dict = {"ts": 0.0, "default_mode": "auto", "groups": {}}


# ── 模式归一化 ──

def normalize_mode(mode: str):
    """将用户输入归一化为内部模式名（auto/always/text），非法输入返回 None。

    兼容别名：voice/on/yes → always；text/off/no → text。
    """
    m = (mode or "").strip().lower()
    if m == "auto":
        return "auto"
    if m in ("always", "voice", "on", "yes", "1"):
        return "always"
    if m in ("text", "off", "no", "0"):
        return "text"
    return None


# ── 内部读写 ──

def _load() -> dict:
    """读取存储文件；不存在或损坏时返回默认结构（不落盘）。"""
    default = {
        "default_mode": plugin_config.group_voice_default,
        "groups": {},
    }
    if not os.path.exists(_PATH):
        return default
    try:
        with open(_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"群语音模式配置读取失败: {e}")
        return default
    if not isinstance(data, dict):
        return default
    data.setdefault("default_mode", plugin_config.group_voice_default)
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
        _cache["default_mode"] = data.get(
            "default_mode", plugin_config.group_voice_default
        )
        _cache["groups"] = dict(data.get("groups", {}))


def _invalidate_cache() -> None:
    """写操作后强制下一次读取重新加载磁盘。"""
    with _lock:
        _cache["ts"] = 0.0


# ── 对外查询 ──

def get_default_mode() -> str:
    """全局默认语音模式（未显式设置的群跟随）。"""
    _refresh_cache()
    return _cache["default_mode"]


def get_group_voice_mode(group_id) -> str:
    """群的语音回复模式。显式设置过的群按设置值，否则跟随全局默认。"""
    gid = str(group_id)
    _refresh_cache()
    groups = _cache.get("groups") or {}
    if gid in groups:
        return groups[gid]
    return _cache["default_mode"]


# ── 对外修改 ──

def set_group_voice_mode(group_id, mode: str) -> bool:
    """设置群语音模式（显式记录）。模式非法时返回 False。"""
    mode = normalize_mode(mode)
    if mode is None:
        return False
    with _lock:
        data = _load()
        data.setdefault("groups", {})
        data["groups"][str(group_id)] = mode
        _save(data)
    _invalidate_cache()
    logger.info(f"群 {group_id} 语音模式已设置为: {mode}")
    return True


def reset_group(group_id) -> None:
    """移除群的显式设置，恢复跟随全局默认。"""
    with _lock:
        data = _load()
        data.setdefault("groups", {})
        data["groups"].pop(str(group_id), None)
        _save(data)
    _invalidate_cache()
    logger.info(f"群 {group_id} 语音模式已恢复跟随全局默认")


def set_default_mode(mode: str) -> bool:
    """设置全局默认语音模式（运行时生效，不写入 .env）。"""
    mode = normalize_mode(mode)
    if mode is None:
        return False
    with _lock:
        data = _load()
        data["default_mode"] = mode
        _save(data)
    _invalidate_cache()
    logger.info(f"全局默认语音模式已设置为: {mode}")
    return True


def list_group_modes() -> dict:
    """返回所有显式设置过的群及其语音模式。"""
    _refresh_cache()
    return dict(_cache.get("groups") or {})
