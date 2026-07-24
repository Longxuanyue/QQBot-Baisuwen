"""
nonebot_plugin_admin - 管理员命令插件

提供系统管理命令：状态查询、配置热重载、记忆管理、休眠控制等。
仅超级用户可执行。
"""

__version__ = "0.2.0"

from nonebot import on_command, logger
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, Message
from nonebot.permission import SUPERUSER
from nonebot.params import CommandArg

from .commands import (
    handle_status, handle_memory_admin,
    handle_reload, handle_sleep_toggle
)

# ── 插件元数据 ──

__plugin_meta__ = PluginMetadata(
    name="管理命令",
    description="提供系统管理命令：状态查询、配置热重载、记忆管理、休眠控制等",
    usage="发送 /admin 查看所有管理子命令；仅超级用户可执行",
    type="application",
    homepage="https://github.com/baisuwen",
    supported_adapters={"~onebot.v11"},
    extra={
        "author": "baisuwen",
        "version": __version__,
    },
)

# ── 主命令 ──

admin = on_command("admin", permission=SUPERUSER, priority=1, block=True)


@admin.handle()
async def handle_admin(bot: Bot, event: MessageEvent, arg: Message = CommandArg()):
    args_text = arg.extract_plain_text().strip()

    if not args_text:
        help_msg = (
            "🔧 管理命令列表 (仅主人可用):\n"
            "/admin status         - 查看服务状态\n"
            "/admin memory <uid>   - 查看用户记忆统计\n"
            "/admin reload [personality|config] - 热重载配置\n"
            "/admin sleep [on|off] - 休眠开关\n"
        )
        await admin.finish(help_msg)

    parts = args_text.split(maxsplit=1)
    sub_cmd = parts[0].lower()
    sub_args = parts[1] if len(parts) > 1 else ""

    if sub_cmd == "status":
        msg = await handle_status()
    elif sub_cmd == "memory":
        msg = await handle_memory_admin(sub_args)
    elif sub_cmd == "reload":
        msg = await handle_reload(sub_args)
    elif sub_cmd == "sleep":
        msg = await handle_sleep_toggle(sub_args)
    else:
        msg = f"未知子命令: {sub_cmd}"

    await admin.finish(msg)
