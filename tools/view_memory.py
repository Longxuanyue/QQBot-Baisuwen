import sqlite3
import os

def view_memories(user_id):
    short_path = f"user_data/short_{user_id}.db"
    long_path = f"user_data/long_{user_id}.db"
    
    for path, name in [(short_path, "短期记忆"), (long_path, "长期记忆")]:
        if not os.path.exists(path):
            print(f"{name} 文件不存在: {path}")
            continue
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, content, importance, strength, access_count FROM memories ORDER BY id")
        rows = cursor.fetchall()
        print(f"\n=== {name} (共{len(rows)}条) ===")
        for row in rows:
            print(f"ID:{row[0]}, 内容:{row[1]}, 重要性:{row[2]:.2f}, 强度:{row[3]:.2f}, 访问次数:{row[4]}")
        conn.close()

if __name__ == "__main__":
    uid = input("请输入用户QQ号: ").strip()
    view_memories(uid)