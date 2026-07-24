"""
向量语义检索（可选功能）。
使用 sentence-transformers 生成嵌入，支持与 FTS5 混合检索。

启用方式：设置环境变量 ENABLE_VECTOR_SEARCH=true
依赖：pip install sentence-transformers
"""

import sqlite3
import os
import struct
import time
from typing import List, Dict, Optional

from .config import SHORT_TERM_DB, LONG_TERM_DB

try:
    from nonebot import logger
except ImportError:
    import logging
    logger = logging.getLogger("memory_embedding")

# 是否启用向量检索（通过环境变量控制）
ENABLE_VECTOR_SEARCH = os.getenv("ENABLE_VECTOR_SEARCH", "false").lower() in (
    "true", "1", "yes"
)

# 惰性加载的模型实例
_embedding_model = None
_EMBEDDING_DIM = 384  # text2vec-base-chinese 输出维度
_EMBEDDING_MODEL_NAME = "shibing624/text2vec-base-chinese"


def _load_model():
    """惰性加载 sentence-transformers 模型"""
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model
    if not ENABLE_VECTOR_SEARCH:
        return None

    try:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer(_EMBEDDING_MODEL_NAME)
        logger.info(f"向量嵌入模型已加载: {_EMBEDDING_MODEL_NAME}")
    except ImportError:
        logger.warning(
            "sentence-transformers 未安装，向量检索不可用。"
            "请运行: pip install sentence-transformers"
        )
        return None
    except Exception as e:
        logger.error(f"加载向量模型失败: {e}")
        return None

    return _embedding_model


def _pack_embedding(embedding: List[float]) -> bytes:
    """将 float 列表打包为 BLOB"""
    return struct.pack(f"{len(embedding)}f", *embedding)


def _unpack_embedding(blob: bytes) -> List[float]:
    """从 BLOB 解包为 float 列表"""
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """计算两个向量的余弦相似度"""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def compute_embedding(text: str) -> Optional[List[float]]:
    """计算文本的嵌入向量"""
    model = _load_model()
    if model is None:
        return None
    embedding = model.encode(text, normalize_embeddings=True)
    return embedding.tolist()


def store_embedding(db_path: str, memory_id: int, content: str) -> bool:
    """为一条记忆存储嵌入向量（后台批量执行）"""
    embedding = compute_embedding(content)
    if embedding is None:
        return False

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    blob = _pack_embedding(embedding)
    cursor.execute(
        "INSERT OR REPLACE INTO memory_vectors (memory_id, embedding) VALUES (?, ?)",
        (memory_id, blob)
    )
    conn.commit()
    conn.close()
    return True


def retrieve_by_embedding(
    db_path: str, query: str, top_k: int = 10
) -> List[Dict]:
    """
    使用余弦相似度进行语义检索。
    如果向量模型不可用，返回空列表。
    """
    query_embedding = compute_embedding(query)
    if query_embedding is None:
        return []

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT v.memory_id, v.embedding, m.content, m.strength, "
        "m.importance, m.access_count, m.last_accessed "
        "FROM memory_vectors v JOIN memories m ON v.memory_id = m.id"
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return []

    # 计算余弦相似度
    scored = []
    for row in rows:
        mem_id, blob, content, strength, importance, acc_count, last_acc = row
        vec = _unpack_embedding(blob)
        sim = _cosine_similarity(query_embedding, vec)
        scored.append((sim, {
            "id": mem_id,
            "content": content,
            "strength": strength,
            "last_accessed": last_acc,
            "access_count": acc_count,
            "importance": importance,
            "source": "vector",
            "score": sim,
            "db_path": db_path,
        }))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:top_k] if item["score"] > 0.0]


def hybrid_retrieve(
    db_path: str, query: str, top_k: int = 5,
    fts_weight: float = 0.4, vec_weight: float = 0.6
) -> List[Dict]:
    """
    混合检索：FTS5 关键词 + 向量语义，加权融合。
    需要同时启用 FTS5 和向量检索。
    """
    from .retrieval import _retrieve_fts5, _bm25_retrieve, _fts5_available

    # FTS5 召回（多召回用于融合）
    if _fts5_available(db_path):
        fts_results = _retrieve_fts5(db_path, query, top_k * 3)
    else:
        fts_results = _bm25_retrieve(db_path, query, top_k * 3, "short")

    # 向量召回
    vec_results = retrieve_by_embedding(db_path, query, top_k * 3)

    # 融合：按 ID 合并分数
    combined: Dict[int, Dict] = {}
    max_fts = max((r["score"] for r in fts_results), default=1.0)
    max_vec = max((r["score"] for r in vec_results), default=1.0)

    for r in fts_results:
        r["combined_score"] = fts_weight * (r["score"] / max(max_fts, 0.001))
        combined[r["id"]] = r

    for r in vec_results:
        vec_score = vec_weight * (r["score"] / max(max_vec, 0.001))
        if r["id"] in combined:
            combined[r["id"]]["combined_score"] += vec_score
        else:
            r["combined_score"] = vec_score
            combined[r["id"]] = r

    # 排序
    sorted_results = sorted(
        combined.values(),
        key=lambda x: x.get("combined_score", 0),
        reverse=True
    )
    return sorted_results[:top_k]
