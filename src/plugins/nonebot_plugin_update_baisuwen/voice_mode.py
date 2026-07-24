"""
语音回复模式切换（仅影响私聊，群聊始终文字回复）

支持三种模式：
- auto:   语音进语音出，文字进文字出（默认）
- always: 总是语音回复（无论用户发文字还是语音）
- text:   总是文字回复（无论用户发文字还是语音）

模式存储在每个用户的 user_preferences 表中。
"""

import sqlite3
import time
import os
from typing import Optional
from nonebot import on_command, logger
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, Message
from nonebot.params import CommandArg

VOICE_MODES = ("auto", "always", "text")


def get_voice_mode(user_id: str, db_path: str = None) -> str:
    """获取用户的语音回复模式"""
    if db_path is None:
        db_path = _get_user_db(user_id)

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT voice_mode FROM user_preferences WHERE user_id = ?",
            (str(user_id),)
        )
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else "auto"
    except sqlite3.OperationalError:
        # 表可能不存在
        return "auto"


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
