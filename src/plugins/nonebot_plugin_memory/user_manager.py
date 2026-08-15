import os
import sqlite3
from typing import List, Dict, Optional
from .config import USER_DATA_DIR, SHORT_TERM_MAX, LONG_TERM_MAX
from .db_init import init_database
from .forgetting import cleanup_memory, sleep_consolidation
from .management import upgrade_and_deduplicate, merge_similar_in_short_term, full_merge_and_manage
from .generation import generate_and_store_memory, store_memory
from .retrieval import retrieve_memories
from .conflict import update_user_info
from .explicit import list_memories

def ensure_user_dir():
    if not os.path.exists(USER_DATA_DIR):
        os.makedirs(USER_DATA_DIR)

def get_user_db_paths(user_id: str):
    """返回 (short_db_path, long_db_path)"""
    ensure_user_dir()
    short_path = os.path.join(USER_DATA_DIR, f"short_{user_id}.db")
    long_path = os.path.join(USER_DATA_DIR, f"long_{user_id}.db")
    return short_path, long_path

class UserMemoryManager:
    """用户记忆管理器（v2：惰性建库）。

    仅在真正发生记忆读写时初始化数据库文件，
    避免"用户说过话但 bot 从未回复"也产生空库文件。
    """

    def __init__(self, user_id: str):
        self.user_id = str(user_id)
        self.short_db, self.long_db = get_user_db_paths(self.user_id)
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """首次真正读写时创建数据库（含 FTS5 表与触发器）"""
        if not self._initialized:
            init_database(self.short_db)
            init_database(self.long_db)
            self._initialized = True

    def store_memory(self, content: str, importance: float = 0.6) -> bool:
        self._ensure_initialized()
        return store_memory(content, importance, self.short_db)

    def generate_and_store_memory(self, user_input: str, assistant_response: str = "") -> Optional[str]:
        self._ensure_initialized()
        return generate_and_store_memory(user_input, assistant_response, self.short_db)

    def retrieve_memories(self, query: str, top_k: int = 5,
                          include_short: bool = True, include_long: bool = True,
                          update_access: bool = True, conversation_history: Optional[List[str]] = None) -> List[Dict]:
        self._ensure_initialized()
        return retrieve_memories(query, top_k, include_short, include_long,
                                 update_access, conversation_history,
                                 db_short=self.short_db, db_long=self.long_db)

    def update_user_info(self, user_input: str) -> bool:
        self._ensure_initialized()
        return update_user_info(user_input, "", self.short_db)

    def cleanup(self):
        self._ensure_initialized()
        cleanup_memory(self.short_db, SHORT_TERM_MAX)
        cleanup_memory(self.long_db, LONG_TERM_MAX)

    def upgrade_and_deduplicate(self):
        self._ensure_initialized()
        upgrade_and_deduplicate(self.short_db, self.long_db)

    def merge_similar(self):
        self._ensure_initialized()
        merge_similar_in_short_term(self.short_db)

    def sleep_consolidation(self):
        self._ensure_initialized()
        sleep_consolidation(self.short_db, self.long_db)

    def full_merge_and_manage(self):
        self._ensure_initialized()
        full_merge_and_manage(self.short_db, self.long_db)

    def memory_count(self) -> int:
        """两个库的记忆条数（不创建文件；用于跳过空库维护）"""
        total = 0
        for db in (self.short_db, self.long_db):
            if not os.path.exists(db):
                continue
            try:
                conn = sqlite3.connect(db)
                try:
                    total += conn.execute(
                        "SELECT COUNT(*) FROM memories"
                    ).fetchone()[0]
                finally:
                    conn.close()
            except sqlite3.OperationalError:
                continue
        return total

    def is_empty(self) -> bool:
        return self.memory_count() == 0

    def get_all_memories(self, limit: int = 100) -> List[Dict]:
        self._ensure_initialized()
        short_rows = list_memories(self.short_db, limit)
        long_rows = list_memories(self.long_db, limit)
        result = []
        for row in short_rows:
            result.append({
                "id": row[0], "content": row[1], "importance": row[2],
                "strength": row[3], "access_count": row[4], "last_accessed": row[5],
                "type": "short"
            })
        for row in long_rows:
            result.append({
                "id": row[0], "content": row[1], "importance": row[2],
                "strength": row[3], "access_count": row[4], "last_accessed": row[5],
                "type": "long"
            })
        return result