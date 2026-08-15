"""
群聊学习存储层：群级 SQLite 库（user_data/group_{gid}.db）

表结构：
- memories / memories_fts / maintenance_state / memory_vectors / user_preferences
    —— 复用 nonebot_plugin_memory.init_database()，群记忆直接继承
       遗忘曲线、FTS5 检索、去重合并等既有能力
- group_messages    群消息流水（供 LLM 批量总结与风格卡）
- group_members     成员统计与昵称学习
- group_topics      话题词频
- group_activity    24 小时活跃直方图
- group_interactions @ 关系计数
- group_meta        KV（开关、氛围分、风格卡、计数等）
"""

import json
import os
import sqlite3
from typing import List, Optional

from ..nonebot_plugin_memory.db_init import init_database

from .config import GROUP_USER_DATA_DIR, GROUP_HISTORY_KEEP


def group_db_path(group_id) -> str:
    """群库文件路径"""
    return os.path.join(GROUP_USER_DATA_DIR, f"group_{group_id}.db")


def init_group_database(db_path: str) -> None:
    """建库：基础表（复用记忆引擎）+ 群学习扩展表"""
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        # 消息流水
        conn.execute(
            "CREATE TABLE IF NOT EXISTS group_messages ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "group_id TEXT NOT NULL,"
            "user_id TEXT NOT NULL,"
            "content TEXT NOT NULL,"
            "ts REAL NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_gm_gid_ts "
            "ON group_messages(group_id, ts)"
        )
        # 成员统计与昵称
        conn.execute(
            "CREATE TABLE IF NOT EXISTS group_members ("
            "member_id TEXT PRIMARY KEY,"
            "nickname TEXT DEFAULT '',"
            "nickname_count INTEGER DEFAULT 0,"
            "msg_count INTEGER DEFAULT 0,"
            "mention_count INTEGER DEFAULT 0,"
            "last_seen REAL DEFAULT 0)"
        )
        # 话题词频
        conn.execute(
            "CREATE TABLE IF NOT EXISTS group_topics ("
            "topic TEXT PRIMARY KEY,"
            "count INTEGER DEFAULT 0,"
            "last_seen REAL DEFAULT 0)"
        )
        # 24 小时活跃
        conn.execute(
            "CREATE TABLE IF NOT EXISTS group_activity ("
            "hour INTEGER PRIMARY KEY,"
            "count INTEGER DEFAULT 0)"
        )
        # @ 关系
        conn.execute(
            "CREATE TABLE IF NOT EXISTS group_interactions ("
            "from_id TEXT NOT NULL,"
            "to_id TEXT NOT NULL,"
            "count INTEGER DEFAULT 0,"
            "PRIMARY KEY (from_id, to_id))"
        )
        # KV
        conn.execute(
            "CREATE TABLE IF NOT EXISTS group_meta ("
            "key TEXT PRIMARY KEY,"
            "value TEXT NOT NULL)"
        )
        conn.commit()
    finally:
        conn.close()


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# ── 消息流水 ──

def insert_messages(db_path: str, rows: List[tuple]) -> None:
    """批量写入消息流水 rows=[(group_id, user_id, content, ts)]"""
    if not rows:
        return
    conn = _connect(db_path)
    try:
        conn.executemany(
            "INSERT INTO group_messages (group_id, user_id, content, ts) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def prune_messages(db_path: str, keep: int = GROUP_HISTORY_KEEP) -> int:
    """清理最旧消息，只保留最近 keep 条，返回删除条数"""
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM group_messages").fetchone()
        total = row[0] if row else 0
        if total <= keep:
            return 0
        cut = total - keep
        conn.execute(
            "DELETE FROM group_messages WHERE id IN ("
            "SELECT id FROM group_messages ORDER BY ts ASC LIMIT ?)",
            (cut,),
        )
        conn.commit()
        return cut
    finally:
        conn.close()


def get_recent_messages(
    db_path: str, limit: int = 500, since_ts: Optional[float] = None
) -> List[dict]:
    """取最近消息（新→旧或旧→新？统一返回时间正序）"""
    conn = _connect(db_path)
    try:
        if since_ts is not None:
            rows = conn.execute(
                "SELECT user_id, content, ts FROM group_messages "
                "WHERE ts >= ? ORDER BY ts ASC LIMIT ?",
                (since_ts, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT user_id, content, ts FROM group_messages "
                "ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
            rows.reverse()
        return [
            {"user_id": r[0], "content": r[1], "ts": r[2]} for r in rows
        ]
    finally:
        conn.close()


# ── 统计表 UPSERT ──

def bump_member(db_path: str, member_id: str, nickname: str, ts: float) -> None:
    """成员消息计数 +1（昵称学习走 update_nickname_counts）"""
    conn = _connect(db_path)
    try:
        if nickname:
            conn.execute(
                "INSERT INTO group_members "
                "(member_id, nickname, nickname_count, msg_count, last_seen) "
                "VALUES (?, ?, 0, 1, ?) "
                "ON CONFLICT(member_id) DO UPDATE SET "
                "msg_count = msg_count + 1, last_seen = excluded.last_seen",
                (member_id, nickname, ts),
            )
        else:
            conn.execute(
                "INSERT INTO group_members (member_id, msg_count, last_seen) "
                "VALUES (?, 1, ?) "
                "ON CONFLICT(member_id) DO UPDATE SET "
                "msg_count = msg_count + 1, last_seen = excluded.last_seen",
                (member_id, ts),
            )
        conn.commit()
    finally:
        conn.close()


def update_nickname_counts(db_path: str, member_id: str, nickname: str) -> None:
    """统计昵称候选出现次数；达标后正式采用"""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT nickname FROM group_members WHERE member_id = ?",
            (member_id,),
        ).fetchone()
        if row and row[0] == nickname:
            return
        # 候选计数存 KV：nick_cand:{member_id}
        key = f"nick_cand:{member_id}"
        row = conn.execute(
            "SELECT value FROM group_meta WHERE key = ?", (key,)
        ).fetchone()
        cand = {}
        if row:
            try:
                cand = json.loads(row[0])
            except (json.JSONDecodeError, TypeError):
                cand = {}
        cand[nickname] = cand.get(nickname, 0) + 1
        if cand[nickname] >= 3:
            # 正式采纳昵称
            conn.execute(
                "UPDATE group_members SET nickname = ?, nickname_count = ? "
                "WHERE member_id = ?",
                (nickname, cand[nickname], member_id),
            )
            conn.execute("DELETE FROM group_meta WHERE key = ?", (key,))
        else:
            conn.execute(
                "INSERT INTO group_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(cand, ensure_ascii=False)),
            )
        conn.commit()
    finally:
        conn.close()


def bump_topic(db_path: str, topic: str, ts: float) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO group_topics (topic, count, last_seen) VALUES (?, 1, ?) "
            "ON CONFLICT(topic) DO UPDATE SET count = count + 1, "
            "last_seen = excluded.last_seen",
            (topic, ts),
        )
        conn.commit()
    finally:
        conn.close()


def bump_activity(db_path: str, hour: int) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO group_activity (hour, count) VALUES (?, 1) "
            "ON CONFLICT(hour) DO UPDATE SET count = count + 1",
            (hour,),
        )
        conn.commit()
    finally:
        conn.close()


def bump_interaction(db_path: str, from_id: str, to_id: str) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO group_interactions (from_id, to_id, count) VALUES (?, ?, 1) "
            "ON CONFLICT(from_id, to_id) DO UPDATE SET count = count + 1",
            (from_id, to_id),
        )
        conn.commit()
    finally:
        conn.close()


# ── KV ──

def set_meta(db_path: str, key: str, value: str) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO group_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def get_meta(db_path: str, key: str, default: str = "") -> str:
    if not os.path.exists(db_path):
        return default
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT value FROM group_meta WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else default
    finally:
        conn.close()


# ── 查询 ──

def list_group_ids() -> List[str]:
    """扫描 user_data 下所有群库 id"""
    if not os.path.isdir(GROUP_USER_DATA_DIR):
        return []
    return sorted(
        f[6:-3]
        for f in os.listdir(GROUP_USER_DATA_DIR)
        if f.startswith("group_") and f.endswith(".db")
    )


def get_group_stats(db_path: str) -> dict:
    """群库统计：记忆数、消息数、成员数、话题、活跃、氛围、风格卡"""
    stats: dict = {}
    if not os.path.exists(db_path):
        return stats
    conn = _connect(db_path)
    try:
        stats["memory_count"] = conn.execute(
            "SELECT COUNT(*) FROM memories"
        ).fetchone()[0]
        stats["message_count"] = conn.execute(
            "SELECT COUNT(*) FROM group_messages"
        ).fetchone()[0]
        stats["member_count"] = conn.execute(
            "SELECT COUNT(*) FROM group_members"
        ).fetchone()[0]
        stats["topics"] = [
            r[0] for r in conn.execute(
                "SELECT topic FROM group_topics ORDER BY count DESC LIMIT 5"
            ).fetchall()
        ]
        stats["active_hours"] = [
            r[0] for r in conn.execute(
                "SELECT hour FROM group_activity ORDER BY count DESC LIMIT 4"
            ).fetchall()
        ]
        stats["members"] = [
            {"id": r[0], "nickname": r[1], "msg_count": r[2]}
            for r in conn.execute(
                "SELECT member_id, nickname, msg_count FROM group_members "
                "ORDER BY msg_count DESC LIMIT 10"
            ).fetchall()
        ]
        stats["style_card"] = get_meta(db_path, "style_card", "")
    finally:
        conn.close()
    return stats


def get_group_memories(db_path: str, limit: int = 100) -> List[dict]:
    """列出群记忆（按权重排序）"""
    if not os.path.exists(db_path):
        return []
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, content, importance, strength, access_count, "
            "last_accessed FROM memories "
            "ORDER BY importance DESC, strength DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": str(r[0]),
                "content": r[1],
                "importance": r[2],
                "strength": r[3],
                "access_count": r[4],
                "last_accessed": r[5],
            }
            for r in rows
        ]
    finally:
        conn.close()


def delete_group_memory(db_path: str, memory_id) -> bool:
    """删除单条群记忆（含 FTS 同步触发器）"""
    if not os.path.exists(db_path):
        return False
    conn = _connect(db_path)
    try:
        cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def clear_group_data(db_path: str) -> int:
    """清空群库全部数据，返回删除的记忆条数"""
    if not os.path.exists(db_path):
        return 0
    conn = _connect(db_path)
    try:
        mem = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        for table in (
            "group_messages", "group_members", "group_topics",
            "group_activity", "group_interactions", "group_meta",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM memories")
        conn.commit()
        return mem
    finally:
        conn.close()
