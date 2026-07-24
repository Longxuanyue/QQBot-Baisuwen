"""
记忆检索：BM25（jieba 分词）/ FTS5 全文搜索 / 混合检索。
优先使用 FTS5，不可用时降级为自定义 BM25。
"""

import os
import sqlite3
import math
import re
from typing import List, Dict, Optional
from .config import SHORT_TERM_DB, LONG_TERM_DB, CONTEXT_HISTORY_LEN
from .forgetting import touch_memory

try:
    from nonebot import logger
except ImportError:
    import logging
    logger = logging.getLogger("memory_retrieval")

try:
    import jieba
    JIEBA_AVAILABLE = True
except ImportError:
    JIEBA_AVAILABLE = False


# ──────────────────────────────────────────────
# Tokenization
# ──────────────────────────────────────────────

def _tokenize(text: str) -> List[str]:
    """分词：优先 jieba，降级为正则"""
    if JIEBA_AVAILABLE:
        words = jieba.lcut(text)
    else:
        words = re.findall(r'[一-龥a-zA-Z0-9]+', text)
    return [w.lower() for w in words if len(w) >= 2]


# ──────────────────────────────────────────────
# BM25 (fallback engine)
# ──────────────────────────────────────────────

class BM25:
    """自定义 BM25 评分器（用于 FTS5 不可用时的降级检索）"""

    def __init__(self, corpus: List[str]):
        self.corpus = corpus
        self.tokenized = [_tokenize(doc) for doc in corpus]
        self.doc_count = len(corpus)
        self.avg_len = sum(len(d) for d in self.tokenized) / max(1, self.doc_count)
        self.idf: Dict[str, float] = {}
        for doc in self.tokenized:
            for token in set(doc):
                self.idf[token] = self.idf.get(token, 0) + 1
        for token, freq in self.idf.items():
            self.idf[token] = math.log(
                (self.doc_count - freq + 0.5) / (freq + 0.5) + 1
            )

    def score(self, query: str) -> List[float]:
        q_tokens = _tokenize(query)
        scores = []
        for doc_tokens in self.tokenized:
            score = 0.0
            doc_len = len(doc_tokens)
            for token in q_tokens:
                if token not in self.idf:
                    continue
                tf = doc_tokens.count(token)
                numerator = tf * (1.5 + 1)
                denominator = tf + 1.5 * (1 - 0.75 + 0.75 * doc_len / self.avg_len)
                score += self.idf[token] * numerator / denominator
            scores.append(score)
        return scores


# ──────────────────────────────────────────────
# FTS5 Retrieval
# ──────────────────────────────────────────────

def _fts5_available(db_path: str) -> bool:
    """检查 FTS5 表是否可用"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM memories_fts LIMIT 1")
        conn.close()
        return True
    except sqlite3.OperationalError:
        return False


def _retrieve_fts5(db_path: str, query: str, top_k: int) -> List[Dict]:
    """
    使用 FTS5 全文搜索检索记忆。
    对中文查询进行 jieba 分词后以 OR 连接，提高召回率。
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # jieba 分词 → FTS5 查询字符串（OR 连接）
    if JIEBA_AVAILABLE:
        tokens = jieba.lcut(query)
        # 过滤停用词和单字
        tokens = [t for t in tokens if len(t) >= 2]
        if tokens:
            fts_query = " OR ".join(tokens)
        else:
            fts_query = query
    else:
        fts_query = query

    try:
        cursor.execute(
            "SELECT m.id, m.content, m.strength, m.last_accessed, "
            "m.access_count, m.importance, rank "
            "FROM memories m JOIN memories_fts f ON m.id = f.rowid "
            "WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
            (fts_query, top_k * 3)  # 多召回一些用于重排序
        )
        rows = cursor.fetchall()
    except sqlite3.OperationalError as e:
        logger.debug(f"FTS5 查询失败，降级到 LIKE: {e}")
        cursor.execute(
            "SELECT id, content, strength, last_accessed, access_count, importance "
            "FROM memories WHERE content LIKE ? LIMIT ?",
            (f"%{query}%", top_k)
        )
        rows = [(r[0], r[1], r[2], r[3], r[4], r[5], 0.0) for r in cursor.fetchall()]

    conn.close()

    results = []
    for row in rows:
        mem_id, content, strength, last_acc, acc_count, importance, fts_rank = row
        results.append({
            "id": mem_id,
            "content": content,
            "strength": strength,
            "last_accessed": last_acc,
            "access_count": acc_count,
            "importance": importance,
            "source": "short" if db_path != LONG_TERM_DB else "long",
            "score": max(0.01, 1.0 / (1.0 + fts_rank)) if fts_rank > 0 else 0.5,
            "db_path": db_path,
        })

    # 按综合得分排序（FTS5 rank + importance 加权）
    results.sort(key=lambda x: x["score"] * x["importance"], reverse=True)
    return results[:top_k]


# ──────────────────────────────────────────────
# 主检索入口
# ──────────────────────────────────────────────

def retrieve_memories(
    query: str,
    top_k: int = 5,
    include_short: bool = True,
    include_long: bool = True,
    update_access: bool = True,
    conversation_history: Optional[List[str]] = None,
    db_short: str = SHORT_TERM_DB,
    db_long: str = LONG_TERM_DB
) -> List[Dict]:
    """
    主检索函数：优先使用 FTS5，降级到 BM25。
    支持上下文感知检索（拼接最近对话历史）。
    """
    # 上下文感知：拼接最近对话
    if conversation_history and CONTEXT_HISTORY_LEN > 0:
        context = " ".join(conversation_history[-CONTEXT_HISTORY_LEN:])
        query = context + " " + query

    all_results = []

    # 短期记忆检索
    if include_short and os.path.exists(db_short):
        if _fts5_available(db_short):
            results = _retrieve_fts5(db_short, query, top_k)
        else:
            results = _bm25_retrieve(db_short, query, top_k, "short")
        all_results.extend(results)

    # 长期记忆检索
    if include_long and os.path.exists(db_long):
        if _fts5_available(db_long):
            results = _retrieve_fts5(db_long, query, top_k)
        else:
            results = _bm25_retrieve(db_long, query, top_k, "long")
        all_results.extend(results)

    # 按 score * importance 排序，取 top_k
    all_results.sort(
        key=lambda x: x.get("score", 0) * x.get("importance", 0.5),
        reverse=True
    )
    top_results = all_results[:top_k]

    # 更新访问记录
    if update_access and top_results:
        for res in top_results:
            touch_memory(res["id"], res["db_path"])

    return top_results


def _bm25_retrieve(db_path: str, query: str, top_k: int, source: str) -> List[Dict]:
    """降级方案：使用自定义 BM25 检索（全表扫描）"""
    if not os.path.exists(db_path):
        return []

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, content, strength, last_accessed, access_count, importance "
        "FROM memories"
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return []

    contents = [r[1] for r in rows]
    bm25 = BM25(contents)
    scores = bm25.score(query)

    indexed = list(enumerate(scores))
    indexed.sort(key=lambda x: x[1], reverse=True)

    results = []
    for idx, score in indexed[:top_k]:
        if score == 0:
            continue
        row = rows[idx]
        results.append({
            "id": row[0],
            "content": row[1],
            "strength": row[2],
            "last_accessed": row[3],
            "access_count": row[4],
            "importance": row[5],
            "source": source,
            "score": score,
            "db_path": db_path,
        })

    return results


# ──────────────────────────────────────────────
# 便捷函数
# ──────────────────────────────────────────────

def retrieve_from_short(
    query: str, top_k: int = 5, update_access: bool = True,
    conversation_history=None, db_path: str = SHORT_TERM_DB
) -> List[Dict]:
    return retrieve_memories(
        query, top_k, True, False, update_access, conversation_history,
        db_short=db_path, db_long=db_path
    )


def retrieve_from_long(
    query: str, top_k: int = 5, update_access: bool = True,
    conversation_history=None, db_path: str = LONG_TERM_DB
) -> List[Dict]:
    return retrieve_memories(
        query, top_k, False, True, update_access, conversation_history,
        db_short=db_path, db_long=db_path
    )
