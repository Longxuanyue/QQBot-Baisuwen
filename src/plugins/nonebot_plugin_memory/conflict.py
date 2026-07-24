import re
import sqlite3
import time
from typing import Optional, Tuple, List
from .config import SHORT_TERM_DB, LONG_TERM_DB, NEGATION_PATTERNS, CHANGE_KEYWORDS
from .retrieval import retrieve_from_short, retrieve_from_long
from .explicit import delete_memory_by_id
from .generation import store_memory
from .management import text_similarity
from .forgetting import touch_memory

try:
    from nonebot import logger
except ImportError:
    import logging
    logger = logging.getLogger("memory_conflict")

# 扩展否定和变更模式
NEGATION_PATTERNS_EXTENDED = NEGATION_PATTERNS + [
    r"不，我其实", r"不是的", r"你记错了", r"纠正一下",
    r"以前.*现在不", r"曾经.*现在",
]
CHANGE_KEYWORDS_EXTENDED = CHANGE_KEYWORDS + ["纠正", "更正", "实际是", "其实是", "准确说是"]

def is_negation(text: str) -> bool:
    for pattern in NEGATION_PATTERNS_EXTENDED:
        if re.search(pattern, text):
            return True
    for kw in CHANGE_KEYWORDS_EXTENDED:
        if kw in text:
            return True
    return False

def extract_fact_from_negation(text: str) -> Optional[str]:
    # 先移除否定词，提取剩余部分
    cleaned = re.sub(r"不(喜欢|爱|想要|需要|希望|愿意|是|会|能)", "", text)
    cleaned = re.sub(r"讨厌|厌恶|不再|已经不是|现在不|不是的|你记错了", "", cleaned)
    for kw in CHANGE_KEYWORDS_EXTENDED:
        if kw in cleaned:
            parts = cleaned.split(kw, 1)
            if len(parts) > 1:
                return parts[1].strip()
    # 提取“以前...现在...”中的现在部分
    match = re.search(r"以前\s*(.+?)\s*现在\s*(.+)", cleaned)
    if match:
        return match.group(2).strip()
    return cleaned.strip()

def find_conflicting_memory(new_content: str, db_path: str, similarity_threshold: float = 0.85) -> Optional[Tuple[int, str, float]]:
    """
    返回 (记忆id, 内容, 当前强度) 如果找到冲突
    """
    if not is_negation(new_content):
        return None
    keywords = re.findall(r'[\u4e00-\u9fa5a-zA-Z0-9]{2,}', new_content)
    if not keywords:
        return None
    search_term = keywords[0] if len(keywords[0]) >= 2 else (keywords[1] if len(keywords) > 1 else None)
    if not search_term:
        return None
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, content, strength FROM memories WHERE content LIKE ? LIMIT 20", (f"%{search_term}%",))
    candidates = cur.fetchall()
    conn.close()
    # 相似度匹配
    for mem_id, content, strength in candidates:
        if text_similarity(new_content, content) >= similarity_threshold:
            return (mem_id, content, strength)
    return None

def resolve_conflict(new_content: str, importance: float = 0.7, db_path: str = SHORT_TERM_DB, 
                     delete_old: bool = True, decay_old_strength: bool = True) -> bool:
    """
    处理冲突：如果存在冲突且新内容是否定/变更，则：
    - 如果 delete_old=True，删除旧记忆
    - 否则，降低旧记忆的强度（乘以0.5）而不删除，然后存储新记忆
    """
    conflict = find_conflicting_memory(new_content, db_path)
    if conflict:
        old_id, old_content, old_strength = conflict
        logger.info(f"冲突检测: 新 '{new_content}' vs 旧 '{old_content}' (强度 {old_strength:.2f})")
        if delete_old:
            delete_memory_by_id(old_id, db_path)
            logger.info("冲突解决: 已删除旧记忆")
        elif decay_old_strength:
            # 降低旧记忆强度
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            new_strength = old_strength * 0.5
            cur.execute("UPDATE memories SET strength = ? WHERE id = ?", (new_strength, old_id))
            conn.commit()
            conn.close()
            logger.info(f"冲突解决: 旧记忆强度降低至 {new_strength:.2f}")
    return store_memory(new_content, importance, db_path)

def update_user_info(user_input: str, assistant_response: str = "", db_path: str = SHORT_TERM_DB,
                     delete_old: bool = False, decay_old_strength: bool = True) -> bool:
    """
    主入口：处理用户信息更新
    参数 delete_old: 是否直接删除旧记忆（默认 False，改为降权）
    """
    if not is_negation(user_input):
        return False
    fact = extract_fact_from_negation(user_input)
    if not fact or len(fact) < 2:
        return False
    return resolve_conflict(fact, importance=0.7, db_path=db_path, 
                            delete_old=delete_old, decay_old_strength=decay_old_strength)