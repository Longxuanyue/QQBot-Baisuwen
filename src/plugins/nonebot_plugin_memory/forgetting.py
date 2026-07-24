import sqlite3
import time
from .config import SHORT_TERM_DB, LONG_TERM_DB, BETA, ETA, WEIGHT_THRESHOLD, SHORT_TERM_MAX, LONG_TERM_MAX

def current_weight(strength: float, last_accessed: float, current_time: float) -> float:
    delta_hours = (current_time - last_accessed) / 3600.0
    return strength * (delta_hours + 1) ** (-BETA)

def touch_memory(memory_id: int, db_path: str = SHORT_TERM_DB, eta: float = ETA) -> None:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT strength FROM memories WHERE id = ?", (memory_id,))
    row = cursor.fetchone()
    if row:
        old_strength = row[0]
        new_strength = min(1.0, old_strength + eta * (1 - old_strength))
        now = time.time()
        cursor.execute(
            "UPDATE memories SET last_accessed = ?, access_count = access_count + 1, strength = ? WHERE id = ?",
            (now, new_strength, memory_id)
        )
        conn.commit()
    conn.close()

def cleanup_memory(db_path: str, max_size: int) -> int:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    now = time.time()
    deleted_total = 0

    cursor.execute("SELECT id, strength, last_accessed FROM memories")
    rows = cursor.fetchall()
    low_weight_ids = []
    for mem_id, strength, last_acc in rows:
        w = current_weight(strength, last_acc, now)
        if w < WEIGHT_THRESHOLD:
            low_weight_ids.append(mem_id)

    if low_weight_ids:
        placeholders = ','.join(['?'] * len(low_weight_ids))
        cursor.execute(f"DELETE FROM memories WHERE id IN ({placeholders})", low_weight_ids)
        deleted_total += len(low_weight_ids)
        conn.commit()

    cursor.execute("SELECT COUNT(*) FROM memories")
    count = cursor.fetchone()[0]
    if count > max_size:
        cursor.execute("SELECT id, strength, last_accessed FROM memories")
        remaining = cursor.fetchall()
        weighted = [(current_weight(strength, last_acc, now), mem_id) for mem_id, strength, last_acc in remaining]
        weighted.sort(key=lambda x: x[0])
        to_delete_count = count - max_size
        to_delete_ids = [mem_id for _, mem_id in weighted[:to_delete_count]]
        if to_delete_ids:
            placeholders = ','.join(['?'] * len(to_delete_ids))
            cursor.execute(f"DELETE FROM memories WHERE id IN ({placeholders})", to_delete_ids)
            deleted_total += len(to_delete_ids)
            conn.commit()

    conn.close()
    return deleted_total

def sleep_consolidation(short_db: str = SHORT_TERM_DB, long_db: str = LONG_TERM_DB):
    conn = sqlite3.connect(short_db)
    cursor = conn.cursor()
    cursor.execute("UPDATE memories SET strength = MIN(1.0, strength * 1.05) WHERE importance > 0.7 OR access_count > 3")
    conn.commit()
    conn.close()

    conn = sqlite3.connect(long_db)
    cursor = conn.cursor()
    cursor.execute("UPDATE memories SET strength = MIN(1.0, strength * 1.01)")
    conn.commit()
    conn.close()