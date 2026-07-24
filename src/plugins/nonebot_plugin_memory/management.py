import sqlite3
import time
import difflib
from collections import defaultdict
from typing import List, Tuple
from .config import (
    SHORT_TERM_DB, LONG_TERM_DB, LONG_TERM_MAX,
    UPGRADE_IMPORTANCE_THRESHOLD, UPGRADE_ACCESS_COUNT_THRESHOLD, UPGRADE_WEIGHT_THRESHOLD,
    SIMILARITY_THRESHOLD, MERGE_SIMILARITY_THRESHOLD
)
from .forgetting import current_weight, cleanup_memory

try:
    from nonebot import logger
except ImportError:
    import logging
    logger = logging.getLogger("memory_management")

try:
    import jieba
    JIEBA_AVAILABLE = True
except ImportError:
    JIEBA_AVAILABLE = False

def text_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()

def is_duplicate_in_long_term(content: str, long_cursor) -> bool:
    long_cursor.execute("SELECT content FROM memories WHERE content = ?", (content,))
    if long_cursor.fetchone():
        return True
    long_cursor.execute("SELECT content FROM memories ORDER BY last_accessed DESC LIMIT 500")
    for (long_content,) in long_cursor.fetchall():
        if text_similarity(content, long_content) >= SIMILARITY_THRESHOLD:
            return True
    return False

def should_upgrade(importance: float, access_count: int, weight: float) -> bool:
    return (importance >= UPGRADE_IMPORTANCE_THRESHOLD or
            access_count >= UPGRADE_ACCESS_COUNT_THRESHOLD or
            weight >= UPGRADE_WEIGHT_THRESHOLD)

def promote_to_long_term(short_mem: Tuple, long_db: str = LONG_TERM_DB) -> bool:
    _, content, importance, strength, created_at, last_accessed, access_count = short_mem
    conn = sqlite3.connect(long_db)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM memories")
    count = cursor.fetchone()[0]
    if count >= LONG_TERM_MAX:
        conn.close()
        deleted = cleanup_memory(long_db, LONG_TERM_MAX)
        if deleted == 0:
            return False
        conn = sqlite3.connect(long_db)
        cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO memories (content, importance, strength, created_at, last_accessed, access_count) VALUES (?, ?, ?, ?, ?, ?)",
            (content, importance, strength, created_at, last_accessed, access_count)
        )
        conn.commit()
        success = True
    except Exception as e:
        logger.error(f"记忆升级失败: {e}")
        success = False
    finally:
        conn.close()
    return success

def upgrade_and_deduplicate(short_db: str = SHORT_TERM_DB, long_db: str = LONG_TERM_DB) -> Tuple[int, int]:
    conn_short = sqlite3.connect(short_db)
    cur_short = conn_short.cursor()
    cur_short.execute("SELECT id, content, importance, strength, created_at, last_accessed, access_count FROM memories")
    short_mems = cur_short.fetchall()
    now = time.time()
    to_delete = []
    upgraded = 0
    duplicated = 0
    conn_long = sqlite3.connect(long_db)
    cur_long = conn_long.cursor()
    for mem in short_mems:
        mem_id, content, importance, strength, created_at, last_accessed, access_count = mem
        if is_duplicate_in_long_term(content, cur_long):
            to_delete.append(mem_id)
            duplicated += 1
            continue
        weight = current_weight(strength, last_accessed, now)
        if should_upgrade(importance, access_count, weight):
            if promote_to_long_term(mem, long_db):
                to_delete.append(mem_id)
                upgraded += 1
    conn_long.close()
    if to_delete:
        placeholders = ','.join(['?'] * len(to_delete))
        cur_short.execute(f"DELETE FROM memories WHERE id IN ({placeholders})", to_delete)
        conn_short.commit()
    conn_short.close()
    logger.info(f"记忆管理: 升级 {upgraded} 条，去重删除 {duplicated} 条")
    return upgraded, duplicated

def _bucket_key(content: str) -> str:
    """生成 hash-bucket 键：使用首个有意义的jieba分词，或内容前两个字符"""
    if JIEBA_AVAILABLE and content:
        words = jieba.lcut(content)
        if words:
            return words[0]
    return content[:2] if content else ""


def merge_similar_in_short_term(short_db: str = SHORT_TERM_DB) -> int:
    """
    合并短期记忆中高度相似的记忆。
    使用 hash-bucket 策略：先按首个分词分桶，仅在桶内做 pairwise 比较，
    将 O(n²) 降为平均 O(n)（桶大小通常很小）。同时使用 quick_ratio() 预筛选。
    """
    conn = sqlite3.connect(short_db)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, content, importance, strength, created_at, last_accessed, access_count "
        "FROM memories"
    )
    all_mem = cursor.fetchall()
    if len(all_mem) < 2:
        conn.close()
        return 0

    # 限制最近 2000 条
    if len(all_mem) > 2000:
        all_mem = all_mem[-2000:]

    # 按首个分词分桶
    buckets: dict = defaultdict(list)
    for mem in all_mem:
        key = _bucket_key(mem[1])
        buckets[key].append(mem)

    to_delete: set = set()

    for bucket in buckets.values():
        bucket_size = len(bucket)
        if bucket_size < 2:
            continue
        for i in range(bucket_size):
            if bucket[i][0] in to_delete:
                continue
            id1, c1, imp1, str1, cr1, last1, acc1 = bucket[i]

            for j in range(i + 1, bucket_size):
                if bucket[j][0] in to_delete:
                    continue
                id2, c2, imp2, str2, cr2, last2, acc2 = bucket[j]

                # 快速预筛选：quick_ratio() 远快于 ratio()
                if difflib.SequenceMatcher(None, c1, c2).quick_ratio() < 0.7:
                    continue
                # 完整相似度比较
                if text_similarity(c1, c2) >= MERGE_SIMILARITY_THRESHOLD:
                    if (imp1 > imp2) or (imp1 == imp2 and acc1 >= acc2):
                        keep_id, keep_acc, keep_last, keep_imp, keep_str = (
                            id1, acc1, last1, imp1, str1
                        )
                        other_id = id2
                    else:
                        keep_id, keep_acc, keep_last, keep_imp, keep_str = (
                            id2, acc2, last2, imp2, str2
                        )
                        other_id = id1
                    new_acc = keep_acc + (acc1 if other_id == id2 else acc2)
                    new_last = max(keep_last, last2 if other_id == id2 else last1)
                    new_imp = max(keep_imp, imp2 if other_id == id2 else imp1)
                    new_str = max(keep_str, str2 if other_id == id2 else str1)
                    cursor.execute(
                        "UPDATE memories SET access_count = ?, last_accessed = ?, "
                        "importance = ?, strength = ? WHERE id = ?",
                        (new_acc, new_last, new_imp, new_str, keep_id)
                    )
                    to_delete.add(other_id)

    if to_delete:
        placeholders = ','.join(['?'] * len(to_delete))
        cursor.execute(f"DELETE FROM memories WHERE id IN ({placeholders})", list(to_delete))
        conn.commit()
    deleted = len(to_delete)
    conn.close()
    if deleted > 0:
        logger.info(f"记忆管理: 合并了 {deleted} 条相似记忆")
    return deleted

def full_merge_and_manage(short_db: str = SHORT_TERM_DB, long_db: str = LONG_TERM_DB):
    logger.info("记忆管理: 开始全表合并处理...")
    merge_similar_in_short_term(short_db)
    upgrade_and_deduplicate(short_db, long_db)

def manage_memories(short_db: str = SHORT_TERM_DB, long_db: str = LONG_TERM_DB):
    return upgrade_and_deduplicate(short_db, long_db)