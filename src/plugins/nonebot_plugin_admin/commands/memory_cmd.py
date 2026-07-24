"""记忆管理命令"""

import os
import sqlite3

from nonebot import logger


async def handle_memory_admin(args: str) -> str:
    """管理用户记忆（查看统计）"""
    user_id = args.strip()
    if not user_id:
        return "请指定用户 QQ 号，如: /admin memory 2461292801"

    try:
        from ...nonebot_plugin_update_baisuwen.config import plugin_config
        user_data_dir = plugin_config.memory.user_data_dir
    except Exception:
        user_data_dir = "user_data"
    lines = [f"📝 用户 {user_id} 记忆统计", ""]

    for db_type, label in [("short", "短期记忆"), ("long", "长期记忆")]:
        db_path = os.path.join(user_data_dir, f"{db_type}_{user_id}.db")
        if not os.path.exists(db_path):
            lines.append(f"{label}: 数据库不存在")
            continue

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 总数统计
        cursor.execute("SELECT COUNT(*), AVG(importance), AVG(strength), "
                       "MAX(access_count) FROM memories")
        count, avg_imp, avg_str, max_acc = cursor.fetchone()

        lines.append(f"--- {label} ---")
        lines.append(f"总数: {count}")
        lines.append(f"平均重要性: {avg_imp:.2f}" if avg_imp else "N/A")
        lines.append(f"平均强度: {avg_str:.2f}" if avg_str else "N/A")
        lines.append(f"最高访问: {max_acc}" if max_acc else "N/A")

        # FTS5 状态
        try:
            cursor.execute("SELECT COUNT(*) FROM memories_fts")
            fts_count = cursor.fetchone()[0]
            lines.append(f"FTS5 索引: {fts_count} 条")
        except sqlite3.OperationalError:
            lines.append("FTS5 索引: 未启用")

        # 最近 3 条高重要性记忆
        cursor.execute(
            "SELECT content, importance, strength FROM memories "
            "ORDER BY importance DESC LIMIT 3"
        )
        top = cursor.fetchall()
        if top:
            lines.append("最近重要记忆:")
            for content, imp, st in top:
                lines.append(f"  [{imp:.2f}/{st:.2f}] {content[:60]}...")

        conn.close()

    return "\n".join(lines)
