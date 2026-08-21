"""
私聊语音回复模式切换（仅影响私聊；群聊语音模式见 group_voice_mode.py，两者互相隔离）

支持三种模式：
- auto:   语音进语音出，文字进文字出（默认）
- always: 总是语音回复（无论用户发文字还是语音）
- text:   总是文字回复（无论用户发文字还是语音）

模式存储在每个用户的 user_preferences 表中。
群聊的回复方式请使用 /群语音（按群设置，不影响任何私聊）。
"""

import sqlite3
import time
import os
from typing import Optional
from nonebot import on_command, logger
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, Message
from nonebot.params import CommandArg

VOICE_MODES = ("auto", "always", "text")

# ── 语音模式内存缓存（避免每次回复都开 SQLite 连接，且不创建空库文件） ──
_mode_cache: dict = {}
_MODE_CACHE_TTL = 60.0  # 秒


def get_voice_mode(user_id: str, db_path: str = None) -> str:
    """获取用户的语音回复模式（带内存缓存）"""
    uid = str(user_id)
    cached = _mode_cache.get(uid)
    if cached and time.time() - cached[1] < _MODE_CACHE_TTL:
        return cached[0]

    mode = "auto"
    if db_path is None:
        db_path = _get_user_db(user_id)

    # 库不存在时不创建文件（用户从未有过记忆库时直接返回默认值）
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT voice_mode FROM user_preferences WHERE user_id = ?",
                (uid,)
            )
            row = cursor.fetchone()
            conn.close()
            mode = row[0] if row else "auto"
        except sqlite3.OperationalError:
            # 表可能不存在
            mode = "auto"

    _mode_cache[uid] = (mode, time.time())
    return mode


def set_voice_mode(user_id: str, mode: str, db_path: str = None) -> bool:
    """设置用户的语音回复模式"""
    if mode not in VOICE_MODES:
        return False

    if db_path is None:
        db_path = _get_user_db(user_id)

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # 确保表存在
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS user_preferences ("
        "user_id TEXT PRIMARY KEY, voice_mode TEXT DEFAULT 'auto', "
        "updated_at REAL NOT NULL)"
    )
    cursor.execute(
        "INSERT OR REPLACE INTO user_preferences (user_id, voice_mode, updated_at) "
        "VALUES (?, ?, ?)",
        (str(user_id), mode, time.time())
    )
    conn.commit()
    conn.close()
    # 写后更新缓存，避免短时间内读到旧值
    _mode_cache[str(user_id)] = (mode, time.time())
    logger.info(f"用户 {user_id} 语音模式切换为: {mode}")
    return True


def _get_user_db(user_id: str) -> str:
    """获取用户数据库路径"""
    from .config import plugin_config
    user_data_dir = plugin_config.memory.user_data_dir
    return os.path.join(user_data_dir, f"short_{user_id}.db")


# ── 命令 ──

voicemode = on_command("voicemode", priority=5, block=True)


@voicemode.handle()
async def handle_voicemode(bot: Bot, event: MessageEvent, arg: Message = CommandArg()):
    mode = arg.extract_plain_text().strip().lower()
    user_id = str(event.user_id)

    if not mode:
        current = get_voice_mode(user_id)
        labels = {"auto": "自动 (语音进→语音出，文字进→文字出)", "always": "总是语音 (仅私聊)",
                   "text": "总是文字"}
        await voicemode.finish(
            f"当前语音模式: {labels.get(current, current)}\n"
            f"可用模式: auto / always / text\n"
            f"切换命令: /voicemode <模式>"
        )

    if mode not in VOICE_MODES:
        await voicemode.finish(
            f"无效模式: {mode}\n"
            f"可用模式: auto / always / text"
        )

    if set_voice_mode(user_id, mode):
        labels = {"auto": "自动模式 (语音进→语音出)", "always": "总是语音模式 (仅私聊)",
                   "text": "总是文字模式"}
        await voicemode.finish(f"✅ 已切换为: {labels.get(mode, mode)}")
    else:
        await voicemode.finish("❌ 切换失败，请稍后再试")
