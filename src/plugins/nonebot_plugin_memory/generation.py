import sqlite3
import time
import re
from typing import Optional, Tuple
from .config import SHORT_TERM_DB, DEFAULT_IMPORTANCE, HIGH_IMPORTANCE_KEYWORDS
from .db_init import init_database

try:
    import jieba
    JIEBA_AVAILABLE = True
except ImportError:
    JIEBA_AVAILABLE = False

# 日志（优先使用 nonebot logger，降级为 print）
try:
    from nonebot import logger
except ImportError:
    import logging
    logger = logging.getLogger("memory_generation")


def _ensure_maintenance_state(db_path: str):
    """确保 maintenance_state 表存在（用于 DB 内计数器）"""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS maintenance_state ("
        "key TEXT PRIMARY KEY, value INTEGER)"
    )
    conn.commit()
    conn.close()


def _increment_and_check(short_db: str):
    """使用 SQLite 表维护计数器，每 500 次添加触发一次合并维护"""
    _ensure_maintenance_state(short_db)
    conn = sqlite3.connect(short_db)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO maintenance_state (key, value) VALUES ('add_count', 1) "
        "ON CONFLICT(key) DO UPDATE SET value = value + 1"
    )
    cursor.execute("SELECT value FROM maintenance_state WHERE key = 'add_count'")
    count = cursor.fetchone()[0]
    if count >= 500:
        from .management import full_merge_and_manage
        full_merge_and_manage(short_db=short_db)
        cursor.execute("UPDATE maintenance_state SET value = 0 WHERE key = 'add_count'")
        logger.debug("记忆维护计数器触发 (count=500)")
    conn.commit()
    conn.close()

def _extract_fact_from_text(text: str) -> Optional[Tuple[str, float]]:
    text = text.strip()
    if not text:
        return None
    importance = DEFAULT_IMPORTANCE
    matched = False
    patterns = [
        (r"(?:我|用户)(?:是|叫|的名字是)\s*(.+?)(?:[。，,\.;；!！？?]|$)", 1.0),
        (r"(?:我|用户)(?:喜欢|喜爱)\s*(.+?)(?:[。，,\.;；!！？?]|$)", 0.9),
        (r"(?:我|用户)(?:讨厌|不喜欢|厌恶)\s*(.+?)(?:[。，,\.;；!！？?]|$)", 0.8),
        (r"(?:我|用户)(?:住在|来自于|在)\s*(.+?)(?:[。，,\.;；!！？?]|$)", 0.9),
        (r"(?:我|用户)(?:会|能|擅长)\s*(.+?)(?:[。，,\.;；!！？?]|$)", 0.7),
        (r"(?:我|用户)(?:不会|不能|不擅长)\s*(.+?)(?:[。，,\.;；!！？?]|$)", 0.7),
    ]
    for pattern, imp in patterns:
        m = re.search(pattern, text)
        if m:
            fact = m.group(1).strip()
            if 2 <= len(fact) <= 100:
                fact = re.sub(r'[。，,\.;；!！？?、：""''（）【】]', '', fact)
                if fact:
                    importance = max(importance, imp)
                    matched = True
                    break
    if not matched:
        for kw in HIGH_IMPORTANCE_KEYWORDS:
            if kw in text:
                idx = text.find(kw) + len(kw)
                remainder = text[idx:].strip()
                end_match = re.search(r'[。，,\.;；!！？?]', remainder)
                if end_match:
                    fact = remainder[:end_match.start()].strip()
                else:
                    fact = remainder
                if fact and 2 <= len(fact) <= 100:
                    fact = re.sub(r'[。，,\.;；!！？?]', '', fact)
                    importance = max(importance, 0.8)
                    matched = True
                    break
    if matched:
        return (fact, importance)
    if JIEBA_AVAILABLE and len(text) < 50:
        import jieba.posseg as pseg
        words = pseg.cut(text)
        nouns = [w.word for w in words if w.flag.startswith('n') and len(w.word) > 1]
        if nouns:
            candidate = max(nouns, key=len)
            if candidate not in ["我", "你", "他", "她", "它"] and 2 <= len(candidate) <= 20:
                return (candidate, DEFAULT_IMPORTANCE * 0.8)
    return None

def _is_duplicate(content: str, db_path: str, hours: int = 24) -> bool:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    now = time.time()
    cutoff = now - hours * 3600
    cursor.execute("SELECT content FROM memories WHERE last_accessed > ?", (cutoff,))
    for (mem,) in cursor.fetchall():
        if mem == content or (len(content) > 5 and content in mem) or (len(mem) > 5 and mem in content):
            conn.close()
            return True
    conn.close()
    return False

def store_memory(content: str, importance: float = DEFAULT_IMPORTANCE, db_path: str = SHORT_TERM_DB) -> bool:
    if not content or len(content) < 2:
        return False
    if _is_duplicate(content, db_path):
        return False
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    now = time.time()
    try:
        initial_strength = min(1.0, importance + 0.2)
        cursor.execute(
            "INSERT INTO memories (content, importance, strength, created_at, last_accessed, access_count) VALUES (?, ?, ?, ?, ?, ?)",
            (content, importance, initial_strength, now, now, 1)
        )
        conn.commit()
        success = True
    except Exception as e:
        logger.error(f"记忆存储失败: {e}")
        success = False
    finally:
        conn.close()
    if success:
        _increment_and_check(db_path)
    return success

def generate_and_store_memory(user_input: str, assistant_response: str = "", db_path: str = SHORT_TERM_DB) -> Optional[str]:
    fact = _extract_fact_from_text(user_input)
    if fact:
        content, imp = fact
        if store_memory(content, imp, db_path):
            return content
    if assistant_response:
        fact = _extract_fact_from_text(assistant_response)
        if fact:
            content, imp = fact
            if store_memory(content, imp, db_path):
                return content
    return None