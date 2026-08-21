"""
按群响应控制命令：/群响应

群内（群主/管理员/超管）：
  /群响应              查看本群响应状态
  /群响应 on|off       开启/关闭本群响应
  /群响应 reset        本群恢复跟随全局默认

超管（任意会话）：
  /群响应 default on|off   设置全局默认（未显式设置的群跟随）
  /群响应 list             列出所有显式设置群的响应状态
  /群响应 on|off <群号>    远程设置指定群
  /群响应 reset <群号>     远程恢复指定群跟随全局默认
"""

from typing import Optional

from nonebot import get_driver, on_command
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageEvent,
)
from nonebot.params import CommandArg

from . import group_response

# ── 命令注册 ──

group_response_cmd = on_command(
    "群响应", aliases={"群回复开关"}, priority=5, block=True,
)

_HELP = (
    "🔔 按群响应控制\n"
    "· 群内命令（群主/管理员/超管）：\n"
    "  /群响应          查看本群状态\n"
    "  /群响应 on|off   开启/关闭本群响应\n"
    "  /群响应 reset    本群跟随全局默认\n"
    "· 超管命令：\n"
    "  /群响应 default on|off   设置全局默认\n"
    "  /群响应 list             查看所有群状态\n"
    "  /群响应 on|off <群号>    远程控制指定群"
)


# ── 权限判断 ──

def _is_superuser(user_id: int) -> bool:
    driver = get_driver()
    return str(user_id) in driver.config.superusers


def _can_manage_group(event: GroupMessageEvent) -> bool:
    """群主/管理员/超管可管理本群响应开关"""
    if event.sender and event.sender.role in ("owner", "admin"):
        return True
    return _is_superuser(event.user_id)


def _on_off_label(enabled: bool) -> str:
    return "✅ 响应中" if enabled else "❌ 已关闭"


def _status_text(gid: Optional[int] = None) -> str:
    default = group_response.get_default_enabled()
    lines = [
        "🔔 按群响应控制",
        f"· 全局默认：{'✅ 响应' if default else '❌ 不响应'}",
    ]
    if gid is not None:
        label = _on_off_label(group_response.is_group_enabled(gid))
        lines.append(f"· 本群（{gid}）：{label}")
    lines.append("· 命令：/群响应 on|off|reset|status（群内）")
    return "\n".join(lines)


# ── 命令处理 ──

@group_response_cmd.handle()
async def handle_group_response(
    event: MessageEvent, arg: Message = CommandArg(),
):
    args_text = arg.extract_plain_text().strip()
    parts: list[str] = args_text.split()
    is_group = isinstance(event, GroupMessageEvent)

    # ── 无参数 / status：查看状态 ──
    if not parts or parts[0] == "status":
        if is_group:
            await group_response_cmd.finish(
                _status_text(event.group_id)
            )
        await group_response_cmd.finish(_HELP)

    sub = parts[0].lower()

    # ── on / off / reset：本群或远程 ──
    if sub in ("on", "off", "reset"):
        enabled = sub == "on"
        if len(parts) >= 2:
            # 远程控制指定群（仅超管）
            if not _is_superuser(event.user_id):
                await group_response_cmd.finish("❌ 仅超级用户可远程控制其他群")
            try:
                target = int(parts[1])
            except ValueError:
                await group_response_cmd.finish(f"❌ 无效的群号: {parts[1]}")
            if sub == "reset":
                group_response.reset_group(target)
                await group_response_cmd.finish(
                    f"✅ 群 {target} 已恢复跟随全局默认"
                )
            group_response.set_group_enabled(target, enabled)
            await group_response_cmd.finish(
                f"✅ 已远程{'开启' if enabled else '关闭'}群 {target} 的响应"
            )
        # 本群操作
        if not is_group:
            await group_response_cmd.finish(
                "❌ 请在本群内使用该命令，或由超管指定群号：/群响应 on|off <群号>"
            )
        if not _can_manage_group(event):
            await group_response_cmd.finish("❌ 仅群主/管理员可修改本群响应开关")
        if sub == "reset":
            group_response.reset_group(event.group_id)
            await group_response_cmd.finish("✅ 本群已恢复跟随全局默认")
        group_response.set_group_enabled(event.group_id, enabled)
        await group_response_cmd.finish(
            f"✅ 本群响应已{'开启' if enabled else '关闭'}"
        )

    # ── default on|off：仅超管 ──
    if sub == "default":
        if not _is_superuser(event.user_id):
            await group_response_cmd.finish("❌ 仅超级用户可修改全局默认")
        if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
            await group_response_cmd.finish(
                "用法：/群响应 default on|off\n"
                "未显式设置的群将跟随该全局默认"
            )
        enabled = parts[1].lower() == "on"
        group_response.set_default_enabled(enabled)
        await group_response_cmd.finish(
            f"✅ 全局默认响应已设置为：{'开' if enabled else '关'}"
        )

    # ── list：仅超管 ──
    if sub == "list":
        if not _is_superuser(event.user_id):
            await group_response_cmd.finish("❌ 仅超级用户可查看所有群状态")
        states = group_response.list_group_states()
        default = group_response.get_default_enabled()
        if not states:
            default_label = "✅ 响应" if default else "❌ 不响应"
            await group_response_cmd.finish(
                f"📋 无显式设置的群（全部跟随全局默认：{default_label}）"
            )
        lines = [
            "📋 按群响应状态",
            f"· 全局默认：{'✅ 响应' if default else '❌ 不响应'}",
        ]
        for gid, enabled in sorted(states.items()):
            lines.append(f"· 群 {gid}：{_on_off_label(enabled)}")
        await group_response_cmd.finish("\n".join(lines))

    await group_response_cmd.finish(_HELP)
