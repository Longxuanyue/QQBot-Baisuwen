"""
Memory Module for Local AI Assistant (多用户支持版 v2)

升级内容：
- FTS5 全文搜索（自动回退到 BM25）
- 向量语义检索（可选，需 sentence-transformers）
- 优化后的 hash-bucket 合并算法
- DB 内计数器（替代文件计数器）
"""

__version__ = "0.2.2"

from nonebot.plugin import PluginMetadata

from .config import (
    SHORT_TERM_DB, LONG_TERM_DB,
    SHORT_TERM_MAX, LONG_TERM_MAX,
    BETA, ETA, WEIGHT_THRESHOLD
)
from .db_init import init_database, migrate_database
from .forgetting import current_weight, touch_memory, cleanup_memory, sleep_consolidation
from .generation import generate_and_store_memory, store_memory
from .management import manage_memories, full_merge_and_manage
from .retrieval import retrieve_memories, retrieve_from_short, retrieve_from_long
from .explicit import delete_memories_by_keyword, delete_memory_by_id, clear_all_memories, list_memories
from .conflict import update_user_info, resolve_conflict
from .backup import backup_all, restore_all
from .user_manager import UserMemoryManager, get_user_db_paths

# 可选模块
try:
    from .embedding import (
        retrieve_by_embedding, hybrid_retrieve,
        compute_embedding, ENABLE_VECTOR_SEARCH
    )
    _HAS_EMBEDDING = True
except ImportError:
    _HAS_EMBEDDING = False

__all__ = [
    "SHORT_TERM_DB", "LONG_TERM_DB", "SHORT_TERM_MAX", "LONG_TERM_MAX",
    "BETA", "ETA", "WEIGHT_THRESHOLD",
    "init_database", "migrate_database",
    "current_weight", "touch_memory", "cleanup_memory", "sleep_consolidation",
    "generate_and_store_memory", "store_memory",
    "manage_memories", "full_merge_and_manage",
    "retrieve_memories", "retrieve_from_short", "retrieve_from_long",
    "delete_memories_by_keyword", "delete_memory_by_id", "clear_all_memories", "list_memories",
    "update_user_info", "resolve_conflict",
    "backup_all", "restore_all",
    "UserMemoryManager", "get_user_db_paths",
    # 向量检索（可选）
    "retrieve_by_embedding", "hybrid_retrieve", "compute_embedding",
    "ENABLE_VECTOR_SEARCH", "_HAS_EMBEDDING",
]

# ── 插件元数据 ──

__plugin_meta__ = PluginMetadata(
    name="记忆系统",
    description="双层记忆系统（短期+长期），支持遗忘曲线、全文检索、向量语义检索、冲突检测与合并",
    usage="内部 library 插件，无直接用户命令；为其他插件提供记忆存储与检索能力",
    type="library",
    homepage="https://github.com/baisuwen",
    supported_adapters={"~onebot.v11"},
    extra={
        "author": "baisuwen",
        "version": __version__,
    },
)