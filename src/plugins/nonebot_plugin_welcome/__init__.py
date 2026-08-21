"""
nonebot_plugin_welcome - 群迎新插件

新成员入群时自动发送欢迎消息（默认内容: 欢迎欢迎~）。
欢迎内容可自由修改，仅超级用户可通过 /迎新 命令设置或重置。

命令:
    /迎新 <内容>    设置新的迎新内容（仅超级用户）
    /迎新           查看当前迎新内容（仅超级用户）
    /迎新 重置      恢复默认内容（仅超级用户）
"""

__version__ = "0.1.0"

import json
from pathlib import Path

from nonebot import logger, on_command, on_notice
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupIncreaseNoticeEvent,
    Message,
    MessageSegment,
)
from nonebot.exception import ActionFailed, ApiNotAvailable, NetworkError
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata

# ── 插件元数据 ──

__plugin_meta__ = PluginMetadata(
    name="群迎新",
    description="新成员入群自动发送欢迎消息，欢迎内容可自由修改（仅超级用户）",
    usage="/迎新 <内容> 设置迎新内容；/迎新 查看当前内容；/迎新 重置 恢复默认",
    type="feature",
    homepage="https://github.com/baisuwen",
    supported_adapters={"~onebot.v11"},
    extra={
        "author": "baisuwen",
        "version": __version__,
        "commands": [
            {"name": "/迎新 <内容>", "description": "自定义群迎新内容（仅超级用户）"},
            {"name": "/迎新", "description": "查看当前迎新内容（仅超级用户）"},
            {"name": "/迎新 重置", "description": "恢复默认迎新内容（仅超级用户）"},
        ],
    },
)

# ── 配置 ──

DEFAULT_WELCOME = "欢迎欢迎~"
MAX_LENGTH = 500

# 数据文件: <项目根>/data/nonebot_plugin_welcome/welcome.json
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DATA_DIR = _PROJECT_ROOT / "data" / "nonebot_plugin_welcome"
_DATA_FILE = _DATA_DIR / "welcome.json"


def _load_welcome() -> str:
    """读取当前迎新内容，未设置或读取失败时返回默认值。"""
    try:
        if _DATA_FILE.exists():
            data = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
            content = data.get("welcome")
            if isinstance(content, str) and content.strip():
                return content
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"[Welcome] 读取欢迎内容失败，使用默认值: {e}")
    return DEFAULT_WELCOME


def _save_welcome(content: str) -> bool:
    """保存迎新内容，返回是否成功。"""
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _DATA_FILE.write_text(
            json.dumps({"welcome": content}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"[Welcome] 保存欢迎内容失败: {e}")
        return False
    return True


# ── 入群迎新（所有用户触发） ──

welcome_notice = on_notice(priority=1, block=False)


@welcome_notice.handle()
async def handle_group_increase(bot: Bot, event: GroupIncreaseNoticeEvent) -> None:
    # 跳过 Bot 自身入群，避免自我欢迎
    if str(event.user_id) == str(event.self_id):
        return

    content = _load_welcome()
    message = MessageSegment.at(event.user_id) + Message(f" {content}")
    try:
        await bot.send(event, message)
    except (ActionFailed, NetworkError, ApiNotAvailable) as e:
        logger.warning(f"[Welcome] 发送迎新消息失败 (group={event.group_id}): {e}")


# ── 修改迎新内容（仅超级用户） ──

welcome_cmd = on_command(
    "迎新",
    permission=SUPERUSER,
    priority=1,
    block=True,
)


@welcome_cmd.handle()
async def handle_welcome_cmd(arg: Message = CommandArg()) -> None:
    args_text = arg.extract_plain_text().strip()

    # 无参数：查看当前内容
    if not args_text:
        msg = (
            "🎉 当前迎新内容：\n"
            f"{_load_welcome()}\n\n"
            "用法：\n"
            "/迎新 <内容> - 设置新的迎新内容\n"
            "/迎新 重置     - 恢复默认内容\n"
            "/迎新          - 查看当前内容"
        )
        await welcome_cmd.finish(msg)

    # 重置为默认
    if args_text in {"重置", "reset"}:
        _save_welcome(DEFAULT_WELCOME)
        await welcome_cmd.finish(f"✅ 已恢复默认迎新内容：\n{DEFAULT_WELCOME}")

    # 长度限制
    if len(args_text) > MAX_LENGTH:
        await welcome_cmd.finish(f"❌ 迎新内容过长，请控制在 {MAX_LENGTH} 字以内")

    if _save_welcome(args_text):
        await welcome_cmd.finish(f"✅ 迎新内容已更新为：\n{args_text}")
    await welcome_cmd.finish("❌ 保存失败，请查看 Bot 日志")
