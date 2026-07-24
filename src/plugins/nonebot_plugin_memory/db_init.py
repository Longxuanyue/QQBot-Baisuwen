"""
数据库初始化：创建表、FTS5 索引、迁移旧表。
"""

import sqlite3
import os
from .config import SHORT_TERM_DB, LONG_TERM_DB, USER_DATA_DIR


def init_database(db_path: str):
    """创建表结构（如果不存在），包括 FTS5 全文搜索虚拟表"""
    # 确保目录存在
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)

    # 基础记忆表
    conn.execute('''
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            importance REAL DEFAULT 0.5,
            strength REAL DEFAULT 0.5,
            created_at REAL NOT NULL,
            last_accessed REAL NOT NULL,
            access_count INTEGER DEFAULT 0
        )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_last_accessed ON memories(last_accessed)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_importance ON memories(importance)')

    # FTS5 全文搜索虚拟表（外部内容表，数据自动同步）
    conn.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
            content,
            content='memories',
            content_rowid='id'
        )
    ''')

    # FTS5 同步触发器：插入
    conn.execute('''
        CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
        END
    ''')

    # FTS5 同步触发器：删除
    conn.execute('''
        CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, content) VALUES('delete', old.id, old.content);
        END
    ''')

    # FTS5 同步触发器：更新
    conn.execute('''
        CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, content) VALUES('delete', old.id, old.content);
            INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
        END
    ''')

    # 维护状态表（替代文件计数器）
    conn.execute('''
        CREATE TABLE IF NOT EXISTS maintenance_state (
            key TEXT PRIMARY KEY,
            value INTEGER
        )
    ''')

    # 向量嵌入表（为语义检索预留）
    conn.execute('''
        CREATE TABLE IF NOT EXISTS memory_vectors (
            memory_id INTEGER PRIMARY KEY,
            embedding BLOB,
            FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
        )
    ''')

    # 对话历史表（为多轮对话管理预留）
    conn.execute('''
        CREATE TABLE IF NOT EXISTS dialog_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_dialog_session ON dialog_history(session_id, timestamp)')

    # 用户偏好表（语音模式等）
    conn.execute('''
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id TEXT PRIMARY KEY,
            voice_mode TEXT DEFAULT 'auto',
            updated_at REAL NOT NULL
        )
    ''')

    conn.commit()
    conn.close()


def migrate_database(db_path: str = None):
    """为旧数据库添加缺失的列和表"""
    if db_path is None:
        paths = [SHORT_TERM_DB, LONG_TERM_DB]
    else:
        paths = [db_path]

    for path in paths:
        if not os.path.exists(path):
            continue

        conn = sqlite3.connect(path)
        cursor = conn.cursor()

        # 添加 strength 列（如果不存在）
        try:
            cursor.execute("ALTER TABLE memories ADD COLUMN strength REAL DEFAULT 0.5")
            cursor.execute("UPDATE memories SET strength = importance WHERE strength IS NULL")
        except sqlite3.OperationalError:
            pass  # 列已存在

        # 创建 FTS5 表（如果是旧库升级）
        try:
            cursor.execute("SELECT 1 FROM memories_fts LIMIT 1")
        except sqlite3.OperationalError:
            # FTS5 表不存在，手动创建
            cursor.execute('''
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                    content,
                    content='memories',
                    content_rowid='id'
                )
            ''')
            # 重建 FTS5 索引：导入现有数据
            cursor.execute("INSERT INTO memories_fts(rowid, content) SELECT id, content FROM memories")
            # 创建触发器
            cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
                END
            ''')
            cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content) VALUES('delete', old.id, old.content);
                END
            ''')
            cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content) VALUES('delete', old.id, old.content);
                    INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
                END
            ''')

        # 创建维护状态表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS maintenance_state (
                key TEXT PRIMARY KEY,
                value INTEGER
            )
        ''')

        # 创建向量表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS memory_vectors (
                memory_id INTEGER PRIMARY KEY,
                embedding BLOB,
                FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
            )
        ''')

        # 创建用户偏好表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id TEXT PRIMARY KEY,
                voice_mode TEXT DEFAULT 'auto',
                updated_at REAL NOT NULL
            )
        ''')

        conn.commit()
        conn.close()


def init_all():
    """初始化单用户模式的数据库（兼容旧接口）"""
    init_database(SHORT_TERM_DB)
    init_database(LONG_TERM_DB)
    migrate_database()
    print("记忆数据库初始化完成")
