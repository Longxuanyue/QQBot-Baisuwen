"""
记忆备份与恢复：导出/导入 JSON
"""

import sqlite3
import json
import os
import time
from typing import Dict, Tuple

from .config import SHORT_TERM_DB, LONG_TERM_DB

try:
    from nonebot import logger
except ImportError:
    import logging
    logger = logging.getLogger("memory_backup")

def export_memories_to_json(db_path: str, json_path: str) -> bool:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, content, importance, strength, created_at, last_accessed, access_count FROM memories")
    rows = cursor.fetchall()
    conn.close()
    data = []
    for row in rows:
        data.append({
            "id": row[0],
            "content": row[1],
            "importance": row[2],
            "strength": row[3],
            "created_at": row[4],
            "last_accessed": row[5],
            "access_count": row[6]
        })
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"导出失败: {e}")
        return False

def import_memories_from_json(db_path: str, json_path: str, clear_existing: bool = True) -> int:
    if not os.path.exists(json_path):
        logger.error(f"文件不存在: {json_path}")
        return 0
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    if clear_existing:
        cursor.execute("DELETE FROM memories")
    imported = 0
    for item in data:
        try:
            cursor.execute(
                "INSERT INTO memories (id, content, importance, strength, created_at, last_accessed, access_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (item["id"], item["content"], item["importance"], item["strength"], item["created_at"], item["last_accessed"], item["access_count"])
            )
            imported += 1
        except sqlite3.IntegrityError:
            continue
    conn.commit()
    conn.close()
    return imported

def backup_all(output_dir: str = "memory_backups") -> Dict[str, str]:
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    timestamp = int(time.time())
    short_path = os.path.join(output_dir, f"short_{timestamp}.json")
    long_path = os.path.join(output_dir, f"long_{timestamp}.json")
    export_memories_to_json(SHORT_TERM_DB, short_path)
    export_memories_to_json(LONG_TERM_DB, long_path)
    return {"short": short_path, "long": long_path}

def restore_all(short_json: str, long_json: str, clear_existing: bool = True) -> Tuple[int, int]:
    short_imported = import_memories_from_json(SHORT_TERM_DB, short_json, clear_existing)
    long_imported = import_memories_from_json(LONG_TERM_DB, long_json, clear_existing)
    return short_imported, long_imported