#!/usr/bin/env python3
"""
记忆管理 CLI 工具

用法:
    python tools/memory_cli.py list <user_id>          列出用户记忆
    python tools/memory_cli.py search <user_id> <query> 搜索记忆
    python tools/memory_cli.py backup <user_id>         备份记忆到 JSON
    python tools/memory_cli.py stats <user_id>          查看记忆统计
    python tools/memory_cli.py clean <user_id>          清理低权重记忆
"""

import sqlite3
import json
import os
import sys
import time
from pathlib import Path

# 项目根目录
ROOT_DIR = Path(__file__).parent.parent
USER_DATA_DIR = ROOT_DIR / "user_data"


def get_db_paths(user_id: str):
    """返回 (short_db_path, long_db_path)"""
    user_id = str(user_id)
    return (
        str(USER_DATA_DIR / f"short_{user_id}.db"),
        str(USER_DATA_DIR / f"long_{user_id}.db"),
    )


def print_memory_row(row, source: str = ""):
    """格式化打印一条记忆"""
    mem_id, content, importance, strength, access_count, *rest = (
        row[0], row[1], row[2], row[3], row[4], row[5:]
    )
    print(f"  [{source}] ID:{mem_id} | 重要性:{importance:.2f} | "
          f"强度:{strength:.2f} | 访问:{access_count} | {content}")


def cmd_list(user_id: str, limit: int = 50):
    """列出用户记忆"""
    short_db, long_db = get_db_paths(user_id)

    for db_path, label in [(short_db, "短期"), (long_db, "长期")]:
        if not os.path.exists(db_path):
            print(f"[!] {label}记忆库不存在: {db_path}")
            continue
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, content, importance, strength, access_count "
            "FROM memories ORDER BY last_accessed DESC LIMIT ?",
            (limit,)
        )
        rows = cursor.fetchall()
        print(f"\n=== {label}记忆 ({len(rows)} 条) ===")
        for row in rows:
            print_memory_row(row, label)
        conn.close()


def cmd_search(user_id: str, query: str, top_k: int = 10):
    """搜索用户记忆"""
    short_db, long_db = get_db_paths(user_id)
    results = []

    for db_path, label in [(short_db, "短期"), (long_db, "长期")]:
        if not os.path.exists(db_path):
            continue
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # 先尝试 FTS5
        try:
            cursor.execute(
                "SELECT m.id, m.content, m.importance, m.strength, m.access_count "
                "FROM memories m JOIN memories_fts f ON m.id = f.rowid "
                "WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
                (query, top_k)
            )
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            # FTS5 不可用，用 LIKE
            cursor.execute(
                "SELECT id, content, importance, strength, access_count "
                "FROM memories WHERE content LIKE ? LIMIT ?",
                (f"%{query}%", top_k)
            )
            rows = cursor.fetchall()
        for row in rows:
            results.append((row, label))
        conn.close()

    if not results:
        print(f"未找到与 '{query}' 相关的记忆")
        return

    results.sort(key=lambda x: x[0][3], reverse=True)  # 按强度排序
    print(f"\n搜索 '{query}' 结果 ({len(results)} 条):")
    for row, label in results[:top_k]:
        print_memory_row(row, label)


def cmd_backup(user_id: str):
    """备份用户记忆到 JSON"""
    short_db, long_db = get_db_paths(user_id)
    backup_dir = ROOT_DIR / "memory_backups"
    backup_dir.mkdir(exist_ok=True)
    timestamp = int(time.time())

    for db_path, label in [(short_db, "short"), (long_db, "long")]:
        if not os.path.exists(db_path):
            print(f"[!] {label}记忆库不存在: {db_path}")
            continue
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, content, importance, strength, created_at, "
            "last_accessed, access_count FROM memories"
        )
        rows = cursor.fetchall()
        conn.close()

        data = []
        for row in rows:
            data.append({
                "id": row[0], "content": row[1], "importance": row[2],
                "strength": row[3], "created_at": row[4],
                "last_accessed": row[5], "access_count": row[6]
            })

        output_path = backup_dir / f"{label}_{user_id}_{timestamp}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[✓] {label}记忆备份到: {output_path} ({len(data)} 条)")


def cmd_stats(user_id: str):
    """查看记忆统计"""
    short_db, long_db = get_db_paths(user_id)

    for db_path, label in [(short_db, "短期"), (long_db, "长期")]:
        if not os.path.exists(db_path):
            print(f"[!] {label}记忆库不存在: {db_path}")
            continue
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), AVG(importance), AVG(strength), "
                       "MAX(access_count), MIN(strength) FROM memories")
        count, avg_imp, avg_str, max_acc, min_str = cursor.fetchone()
        print(f"\n--- {label}记忆统计 ---")
        print(f"  总数: {count:,}")
        print(f"  平均重要性: {avg_imp:.2f}" if avg_imp else "  平均重要性: N/A")
        print(f"  平均强度: {avg_str:.2f}" if avg_str else "  平均强度: N/A")
        print(f"  最高访问次数: {max_acc}" if max_acc else "  最高访问次数: N/A")
        print(f"  最低强度: {min_str:.2f}" if min_str else "  最低强度: N/A")
        conn.close()


def cmd_clean(user_id: str):
    """清理低权重记忆"""
    short_db, long_db = get_db_paths(user_id)

    for db_path, label in [(short_db, "短期"), (long_db, "长期")]:
        if not os.path.exists(db_path):
            continue
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        now = time.time()

        # 使用幂律衰减计算权重并清理
        cursor.execute("SELECT id, strength, last_accessed FROM memories")
        rows = cursor.fetchall()
        low_ids = []
        for mem_id, strength, last_acc in rows:
            delta_hours = (now - last_acc) / 3600.0
            weight = strength * (delta_hours + 1) ** (-0.5)
            if weight < 0.1:
                low_ids.append(mem_id)

        if low_ids:
            placeholders = ','.join(['?'] * len(low_ids))
            cursor.execute(f"DELETE FROM memories WHERE id IN ({placeholders})", low_ids)
            conn.commit()
            print(f"[✓] {label}记忆清理完成: 删除 {len(low_ids)} 条低权重记忆")
        else:
            print(f"[✓] {label}记忆: 无需清理")
        conn.close()


def print_usage():
    print(__doc__)


def main():
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "list":
        if len(sys.argv) < 3:
            print("用法: python tools/memory_cli.py list <user_id>")
            sys.exit(1)
        cmd_list(sys.argv[2])

    elif command == "search":
        if len(sys.argv) < 4:
            print("用法: python tools/memory_cli.py search <user_id> <query>")
            sys.exit(1)
        cmd_search(sys.argv[2], sys.argv[3])

    elif command == "backup":
        if len(sys.argv) < 3:
            print("用法: python tools/memory_cli.py backup <user_id>")
            sys.exit(1)
        cmd_backup(sys.argv[2])

    elif command == "stats":
        if len(sys.argv) < 3:
            print("用法: python tools/memory_cli.py stats <user_id>")
            sys.exit(1)
        cmd_stats(sys.argv[2])

    elif command == "clean":
        if len(sys.argv) < 3:
            print("用法: python tools/memory_cli.py clean <user_id>")
            sys.exit(1)
        cmd_clean(sys.argv[2])

    else:
        print(f"未知命令: {command}")
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
