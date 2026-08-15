"""
记忆检索：FTS5 双表（unicode61 英文 + trigram 中文子串）/ LIKE 降级 / BM25 兜底。

v3 优化：
- trigram 表：中文任意子串匹配（"咖啡" 命中 "用户喜欢喝咖啡"）
- 空结果自动降级链：FTS → LIKE（核心词）→（FTS 不可用时）BM25
- 别名扩展：内置别名表 + 调用方传入的群级别名
- 向量语义融合（可选）：RRF 融合，ENABLE_VECTOR_SEARCH 且向量表非空时生效
"""

import math
import os
import re
import sqlite3
import time
from typing import Dict, List, Optional

from .config import (
    SHORT_TERM_DB, LONG_TERM_DB, CONTEXT_HISTORY_LEN, ETA,
)
from .text_utils import (
    normalize_text, tokenize as _cached_tokenize,
    expand_query,
)

try:
    from nonebot import logger
except ImportError:
    import logging
    logger = logging.getLogger("memory_retrieval")

# FTS 可用性缓存（建表后固定不变，避免每次检索重复探测）
_FTS_AVAILABLE_CACHE: dict = {}
_FTS_TRIGRAM_CACHE: dict = {}

# ── 中英文判定 ──

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def _has_ascii(text: str) -> bool:
    return bool(re.search(r"[a-zA-Z0-9]", text))


# ──────────────────────────────────────────────
# Tokenization（统一走 text_utils，带 lru_cache 与领域/动态词典）
# ──────────────────────────────────────────────

def _tokenize(text: str) -> List[str]:
    return list(_cached_tokenize(text))


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
# FTS 可用性
# ──────────────────────────────────────────────

def _fts5_available(db_path: str) -> bool:
    """unicode61 表可用性（缓存）"""
    cached = _FTS_AVAILABLE_CACHE.get(db_path)
    if cached is not None:
        return cached
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM memories_fts LIMIT 1")
        conn.close()
        _FTS_AVAILABLE_CACHE[db_path] = True
        return True
    except sqlite3.OperationalError:
        _FTS_AVAILABLE_CACHE[db_path] = False
        return False


def _fts_trigram_available(db_path: str) -> bool:
    """trigram 表可用性（缓存）"""
    cached = _FTS_TRIGRAM_CACHE.get(db_path)
    if cached is not None:
        return cached
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM memories_fts_trigram LIMIT 1")
        conn.close()
        _FTS_TRIGRAM_CACHE[db_path] = True
        return True
    except sqlite3.OperationalError:
        _FTS_TRIGRAM_CACHE[db_path] = False
        return False


# ──────────────────────────────────────────────
# 查询构造
# ──────────────────────────────────────────────

def _build_query_tokens(query: str, extra_aliases: Optional[dict] = None) -> List[str]:
    """构造查询词集：jieba token + 别名扩展词（去重、长度过滤）"""
    norm = normalize_text(query)
    tokens = [t for t in _tokenize(norm) if len(t) >= 2]
    aliases = expand_query(norm, extra_aliases)
    seen = set()
    result = []
    for w in tokens + aliases:
        w = w.strip()
        if w and w not in seen:
            seen.add(w)
            result.append(w)
    return result


def _like_fallback(
    cursor, query: str, top_k: int, extra_aliases: Optional[dict] = None
) -> List:
    """LIKE 降级：核心词 + 别名扩展词 + 整句前 20 字符"""
    norm = normalize_text(query)
    tokens = _tokenize(norm)
    aliases = expand_query(norm, extra_aliases)
    candidates = list(tokens) + aliases
    if norm:
        candidates.append(norm[:20])
    seen_ids = set()
    rows = []
    for cand in candidates:
        # 单字符候选（如别名"粥"）对 LIKE 依然有效，仅排除空串
        if not cand:
            continue
        cursor.execute(
            "SELECT id, content, strength, last_accessed, access_count, importance "
            "FROM memories WHERE content LIKE ? LIMIT ?",
            (f"%{cand}%", top_k),
        )
        for r in cursor.fetchall():
            if r[0] not in seen_ids:
                seen_ids.add(r[0])
                rows.append(r + (0.0,))
        if len(rows) >= top_k:
            break
    return rows


# ──────────────────────────────────────────────
# 批量 touch
# ──────────────────────────────────────────────

def _batch_touch(cursor: sqlite3.Cursor, results: list) -> None:
    """批量更新命中记忆的访问时间与强度（单连接内执行）"""
    now = time.time()
    for res in results:
        mem_id = res["id"]
        old_strength = res.get("strength", 0.5)
        new_strength = min(1.0, old_strength + ETA * (1 - old_strength))
        cursor.execute(
            "UPDATE memories SET last_accessed = ?, "
            "access_count = access_count + 1, strength = ? WHERE id = ?",
            (now, new_strength, mem_id),
        )


def _rows_to_results(rows: List, db_path: str) -> List[Dict]:
    """原始行 → 结果 dict（rows 结构：id, content, strength, last_acc, acc_count, importance, rank）"""
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
    return results


def _retrieve_fts5(
    db_path: str, query: str, top_k: int, update_access: bool = True,
    extra_aliases: Optional[dict] = None,
) -> List[Dict]:
    """
    主检索：unicode61（英文）+ trigram（中文子串）+ LIKE 降级。

    降级链：FTS 双表 →（空结果）→ LIKE 核心词。
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    norm = normalize_text(query)
    tokens = _build_query_tokens(query, extra_aliases)
    raw_rows: List = []

    # 1) unicode61 表（英文/数字，以及中文整词匹配）
    if _fts5_available(db_path) and tokens:
        fts_query = " OR ".join(tokens)
        try:
            cursor.execute(
                "SELECT m.id, m.content, m.strength, m.last_accessed, "
                "m.access_count, m.importance, rank "
                "FROM memories m JOIN memories_fts f ON m.id = f.rowid "
                "WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
                (fts_query, top_k * 3)
            )
            raw_rows.extend(cursor.fetchall())
        except sqlite3.OperationalError as e:
            logger.debug(f"unicode61 查询失败，降级 LIKE: {e}")
        except sqlite3.DatabaseError:
            pass

    # 2) trigram 表（中文子串；token 需 >= 3 字符）
    if _fts_trigram_available(db_path):
        tri_tokens = [t for t in tokens if len(t) >= 3]
        if tri_tokens:
            tri_query = " OR ".join(tri_tokens)
            try:
                cursor.execute(
                    "SELECT m.id, m.content, m.strength, m.last_accessed, "
                    "m.access_count, m.importance, bm25(memories_fts_trigram) "
                    "FROM memories m JOIN memories_fts_trigram f ON m.id = f.rowid "
                    "WHERE memories_fts_trigram MATCH ? ORDER BY rank LIMIT ?",
                    (tri_query, top_k * 3)
                )
                raw_rows.extend(cursor.fetchall())
            except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
                logger.debug(f"trigram 查询失败: {e}")

    # 3) 空结果 → LIKE 核心词降级（含别名扩展词）
    if not raw_rows:
        try:
            raw_rows = _like_fallback(
                cursor, norm or query, top_k, extra_aliases
            )
        except sqlite3.OperationalError:
            raw_rows = []

    # 去重（双表可能重复命中同一记忆）
    seen_ids = set()
    dedup = []
    for r in raw_rows:
        if r[0] not in seen_ids:
            seen_ids.add(r[0])
            dedup.append(r)

    results = _rows_to_results(dedup, db_path)
    results.sort(key=lambda x: x["score"] * x["importance"], reverse=True)
    top = results[:top_k]

    # 批量更新访问记录（复用当前连接）
    if update_access and top:
        _batch_touch(cursor, top)
        conn.commit()

    conn.close()
    return top


# ──────────────────────────────────────────────
# 向量语义融合（可选）
# ──────────────────────────────────────────────

def _vector_search_enabled(db_path: str) -> bool:
    """向量检索可用：开关开启 且 向量表非空（避免在检索路径触发模型下载）"""
    try:
        from .embedding import ENABLE_VECTOR_SEARCH
        if not ENABLE_VECTOR_SEARCH:
            return False
        if not os.path.exists(db_path):
            return False
        conn = sqlite3.connect(db_path)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM memory_vectors"
            ).fetchone()[0]
        finally:
            conn.close()
        return n > 0
    except Exception:
        return False


def _rrf_fuse(result_lists: List[List[Dict]], k: int = 60) -> List[Dict]:
    """Reciprocal Rank Fusion：多来源排序融合"""
    scores: Dict[tuple, float] = {}
    items: Dict[tuple, Dict] = {}
    for lst in result_lists:
        for rank, item in enumerate(lst):
            key = (item.get("db_path", ""), item.get("id"))
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            items.setdefault(key, item)
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    result = []
    for key, score in ranked:
        item = dict(items[key])
        item["score"] = score
        result.append(item)
    return result


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
    db_long: str = LONG_TERM_DB,
    extra_aliases: Optional[dict] = None,
) -> List[Dict]:
    """
    主检索函数：FTS 双表 → LIKE → BM25 降级；可选向量 RRF 融合。

    支持上下文感知（拼接最近对话）与别名扩展。
    """
    # 上下文感知：拼接最近对话（指代消解："那个活动" → 前文主题）
    if conversation_history and CONTEXT_HISTORY_LEN > 0:
        context = " ".join(conversation_history[-CONTEXT_HISTORY_LEN:])
        query = context + " " + query

    lists: List[List[Dict]] = []

    # 短期记忆检索
    if include_short and os.path.exists(db_short):
        if _fts5_available(db_short) or _fts_trigram_available(db_short):
            lists.append(_retrieve_fts5(
                db_short, query, top_k, update_access,
                extra_aliases=extra_aliases,
            ))
        else:
            lists.append(_bm25_retrieve(
                db_short, query, top_k, "short", update_access
            ))
        if _vector_search_enabled(db_short):
            lists.append(_vector_retrieve(db_short, query, top_k))

    # 长期记忆检索
    if include_long and os.path.exists(db_long):
        if _fts5_available(db_long) or _fts_trigram_available(db_long):
            lists.append(_retrieve_fts5(
                db_long, query, top_k, update_access,
                extra_aliases=extra_aliases,
            ))
        else:
            lists.append(_bm25_retrieve(
                db_long, query, top_k, "long", update_access
            ))
        if _vector_search_enabled(db_long):
            lists.append(_vector_retrieve(db_long, query, top_k))

    if not lists:
        return []

    # 向量存在时用 RRF 融合，否则按 score*importance 排序
    if any("vector" in str(r.get("source", "")) for lst in lists for r in lst):
        fused = _rrf_fuse(lists)
    else:
        fused = sorted(
            (r for lst in lists for r in lst),
            key=lambda x: x.get("score", 0) * x.get("importance", 0.5),
            reverse=True,
        )
    return fused[:top_k]


def _vector_retrieve(db_path: str, query: str, top_k: int) -> List[Dict]:
    """向量检索（模型不可用/表空时返回空列表）"""
    try:
        from .embedding import retrieve_by_embedding
        return retrieve_by_embedding(db_path, query, top_k * 2)
    except Exception as e:
        logger.debug(f"向量检索失败: {e}")
        return []


def _bm25_retrieve(
    db_path: str, query: str, top_k: int, source: str,
    update_access: bool = True,
) -> List[Dict]:
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

    if not rows:
        conn.close()
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

    # 批量更新访问记录（复用当前连接）
    if update_access and results:
        _batch_touch(cursor, results)
        conn.commit()

    conn.close()
    return results


# ──────────────────────────────────────────────
# 便捷函数
# ──────────────────────────────────────────────

def retrieve_from_short(
    query: str, top_k: int = 5, update_access: bool = True,
    conversation_history=None, db_path: str = SHORT_TERM_DB,
    extra_aliases: Optional[dict] = None,
) -> List[Dict]:
    return retrieve_memories(
        query, top_k, True, False, update_access, conversation_history,
        db_short=db_path, db_long=db_path, extra_aliases=extra_aliases,
    )


def retrieve_from_long(
    query: str, top_k: int = 5, update_access: bool = True,
    conversation_history=None, db_path: str = LONG_TERM_DB,
    extra_aliases: Optional[dict] = None,
) -> List[Dict]:
    return retrieve_memories(
        query, top_k, False, True, update_access, conversation_history,
        db_short=db_path, db_long=db_path, extra_aliases=extra_aliases,
    )
