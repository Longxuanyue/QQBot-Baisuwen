import sqlite3
import re
from typing import List, Tuple
from .config import SHORT_TERM_DB, LONG_TERM_DB

def delete_memories_by_keyword(keyword: str, db_path: str, use_regex: bool = False) -> int:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    if use_regex:
        cursor.execute("SELECT id, content FROM memories")
        rows = cursor.fetchall()
        to_delete = [rid for rid, content in rows if re.search(keyword, content, re.IGNORECASE)]
        if to_delete:
            placeholders = ','.join(['?'] * len(to_delete))
            cursor.execute(f"DELETE FROM memories WHERE id IN ({placeholders})", to_delete)
            deleted = len(to_delete)
        else:
            deleted = 0
    else:
        cursor.execute("DELETE FROM memories WHERE content LIKE ?", (f"%{keyword}%",))
        deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted

def delete_memory_by_id(memory_id: int, db_path: str) -> bool:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def clear_all_memories(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM memories")
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted

def list_memories(db_path: str, limit: int = 50, order_by: str = "last_accessed DESC") -> List[Tuple]:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(f"SELECT id, content, importance, strength, access_count, last_accessed FROM memories ORDER BY {order_by} LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def delete_from_both(keyword: str, use_regex: bool = False) -> Tuple[int, int]:
    short_del = delete_memories_by_keyword(keyword, SHORT_TERM_DB, use_regex)
    long_del = delete_memories_by_keyword(keyword, LONG_TERM_DB, use_regex)
    return short_del, long_del