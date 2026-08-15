"""
群上下文构建：把群记忆、风格卡、统计、昵称组装成一段"群上下文块"，
注入 system prompt，预算受 GROUP_CONTEXT_MAX_TOKENS 限制。
"""

import json
import os
import time
from typing import Optional

from ..nonebot_plugin_update_baisuwen.token_budget import truncate_text

from . import storage
from .config import (
    GROUP_CONTEXT_MAX_TOKENS, GROUP_MEMORY_TOP_K,
)
from .summarizer import retrieve_group_memories

# 昵称查询内存缓存（防频繁读库）：{group_id: {uid: nickname}}
_nick_cache: dict = {}
_NICK_CACHE_TTL = 120.0
_nick_cache_ts: dict = {}


def _load_nicknames(group_id) -> dict:
    """加载群昵称映射（带 TTL 缓存）"""
    gid = str(group_id)
    now = time.time()
    if gid in _nick_cache and now - _nick_cache_ts.get(gid, 0) < _NICK_CACHE_TTL:
        return _nick_cache[gid]
    db_path = storage.group_db_path(gid)
    result: dict = {}
    if os.path.exists(db_path):
        try:
            import sqlite3
            conn = sqlite3.connect(db_path)
            try:
                rows = conn.execute(
                    "SELECT member_id, nickname FROM group_members "
                    "WHERE nickname != '' AND nickname_count >= 1"
                ).fetchall()
                result = {r[0]: r[1] for r in rows}
            finally:
                conn.close()
        except Exception:
            pass
    _nick_cache[gid] = result
    _nick_cache_ts[gid] = now
    return result


def get_nickname(group_id, user_id: str) -> str:
    """获取群内昵称（无则返回空串）"""
    nicks = _load_nicknames(group_id)
    return nicks.get(str(user_id), "")


def format_speaker(group_id, user_id: str) -> str:
    """说话人标注：昵称优先，否则 QQ 号"""
    nick = get_nickname(group_id, user_id)
    return nick or str(user_id)


def _parse_style_card(db_path: str) -> Optional[dict]:
    raw = storage.get_meta(db_path, "style_card", "")
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def build_group_context(group_id, msg_text: str) -> str:
    """构建群上下文块（≤ GROUP_CONTEXT_MAX_TOKENS token）"""
    gid = str(group_id)
    db_path = storage.group_db_path(gid)
    if not os.path.exists(db_path):
        return ""

    parts: list = []

    # 1. 风格卡
    card = _parse_style_card(db_path)
    if card:
        tone = card.get("tone", "")
        habits = card.get("habits", [])
        card_topics = card.get("topics", [])
        if tone:
            line = f"群氛围：{tone}"
            if habits:
                line += "（" + "；".join(habits[:2]) + "）"
            parts.append(line)
        if card_topics:
            parts.append(f"群内高频话题：{'、'.join(card_topics[:3])}")

    # 2. 今日话题（统计）
    stats = storage.get_group_stats(db_path)
    topics = stats.get("topics", [])
    if topics:
        parts.append(f"近期话题：{'、'.join(topics[:3])}")

    # 3. 群记忆（复用记忆引擎检索）
    memories = retrieve_group_memories(gid, msg_text, GROUP_MEMORY_TOP_K)
    if memories:
        mem_lines = "；".join(f"- {m['content']}" for m in memories[:3])
        parts.append(f"群记忆：{mem_lines}")

    # 4. 昵称映射（最多 3 个）
    nicks = _load_nicknames(gid)
    if nicks:
        nick_pairs = "、".join(
            f"{uid}叫{nick}" for uid, nick in list(nicks.items())[:3]
        )
        parts.append(f"群昵称：{nick_pairs}")

    if not parts:
        return ""

    text = "【群上下文】\n" + "\n".join(parts)
    return truncate_text(text, GROUP_CONTEXT_MAX_TOKENS)
