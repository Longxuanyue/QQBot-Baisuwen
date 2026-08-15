"""
空记忆库清理工具

背景：旧版本会在"用户发言但 bot 未回复"时也创建 short_/long_ 数据库文件，
导致 user_data/ 下堆积大量 0 条记忆的空库（含 WAL 影子文件）。
v2 已改为惰性建库，本工具用于清理历史遗留。

用法：
    python tools/cleanup_empty_dbs.py [--dir user_data] [--dry-run]
"""

import argparse
import sqlite3
import sys
from pathlib import Path

DB_PREFIXES = ("short_", "long_")


def is_empty_db(path: Path) -> bool:
    """数据库是否为 0 条记忆（表缺失也视为空）"""
    try:
        conn = sqlite3.connect(path)
        try:
            count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            return count == 0
        finally:
            conn.close()
    except sqlite3.OperationalError:
        return True
    except sqlite3.DatabaseError:
        return True


def cleanup(user_data_dir: Path, *, dry_run: bool) -> int:
    """扫描并删除空库，返回删除数量"""
    removed = 0
    kept = 0
    db_paths = sorted(user_data_dir.glob("short_*.db")) + sorted(
        user_data_dir.glob("long_*.db")
    )
    for db_path in db_paths:
        if is_empty_db(db_path):
            if dry_run:
                print(f"[dry-run] 将删除空库: {db_path.name}")  # noqa: T201
            else:
                db_path.unlink()
                # 顺带清理 WAL / SHM 影子文件
                for suffix in ("-wal", "-shm"):
                    shadow = Path(str(db_path) + suffix)
                    if shadow.exists():
                        shadow.unlink()
                print(f"已删除空库: {db_path.name}")  # noqa: T201
            removed += 1
        else:
            kept += 1
    print(  # noqa: T201
        f"统计: 删除 {removed} 个空库, 保留 {kept} 个有效库 "
        f"(目录: {user_data_dir})"
    )
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="清理 0 条记忆的空数据库文件")
    parser.add_argument("--dir", default="user_data", help="user_data 目录路径")
    parser.add_argument(
        "--dry-run", action="store_true", help="仅列出将删除的文件，不实际删除"
    )
    args = parser.parse_args()

    data_dir = Path(args.dir)
    if not data_dir.is_dir():
        print(f"错误: 目录不存在: {data_dir}", file=sys.stderr)  # noqa: T201
        return 1

    cleanup(data_dir, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
