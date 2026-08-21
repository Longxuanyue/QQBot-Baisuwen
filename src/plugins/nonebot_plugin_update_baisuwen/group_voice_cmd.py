"""
按群语音回复模式命令：/群语音

群内（群主/管理员/超管）：
  /群语音                查看本群语音回复模式
  /群语音 auto           自动（语音进→语音出，文字进→文字出）
  /群语音 voice          本群总是语音回复（同 always/on）
  /群语音 text           本群总是文字回复（同 off）
  /群语音 reset          本群恢复跟随全局默认

超管（任意会话）：
  /群语音 default auto|voice|text   设置全局默认模式
  /群语音 list                     列出所有显式设置群的模式
  /群语音 <模式> <群号>             远程设置指定群

说明：群聊语音模式与私聊（/voicemode）互相隔离，互不影响。
"""

from typing import Optional

from nonebot import get_driver, on_command
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageEvent,
)
from nonebot.params import CommandArg

from . import group_voice_mode

# ── 命令注册 ──

group_voice_cmd = on_command(
    "群语音", aliases={"群语音模式"}, priority=5, block=True,
)

_LABELS = {
    "auto": "自动（语音进→语音出，文字进→文字出）",
    "always": "总是语音",
    "text": "总是文字",
}

_HELP = (
    "🎙 按群语音回复模式\n"
    "· 群内命令（群主/管理员/超管）：\n"
    "  /群语音            查看本群模式\n"
    "  /群语音 auto       自动（语音进→语音出）\n"
    "  /群语音 voice      本群总是语音回复\n"
    "  /群语音 text       本群总是文字回复\n"
    "  /群语音 reset      本群跟随全局默认\n"
    "· 超管命令：\n"
    "  /群语音 default auto|voice|text   设置全局默认\n"
    "  /群语音 list       查看所有群模式\n"
    "  /群语音 <模式> <群号>   远程设置指定群\n"
    "· 与私聊 /voicemode 互相隔离，互不影响"
)


# ── 权限判断 ──

def _is_superuser(user_id: int) -> bool:
    driver = get_driver()
    return str(user_id) in driver.config.superusers


def _can_manage_group(event: GroupMessageEvent) -> bool:
    """群主/管理员/超管可管理本群语音模式"""
    if event.sender and event.sender.role in ("owner", "admin"):
        return True
    return _is_superuser(event.user_id)


def _mode_label(mode: str) -> str:
    return _LABELS.get(mode, mode)


def _status_text(gid: Optional[int] = None) -> str:
    default = group_voice_mode.get_default_mode()
    lines = [
        "🎙 按群语音回复模式",
        f"· 全局默认：{_mode_label(default)}",
    ]
    if gid is not None:
        lines.append(
            f"· 本群（{gid}）："
            f"{_mode_label(group_voice_mode.get_group_voice_mode(gid))}"
        )
    lines.append("· 命令：/群语音 auto|voice|text|reset（群内）")
    return "\n".join(lines)


# ── 命令处理 ──

@group_voice_cmd.handle()
async def handle_group_voice_mode(
    event: MessageEvent, arg: Message = CommandArg(),
):
    args_text = arg.extract_plain_text().strip()
    parts: list[str] = args_text.split()
    is_group = isinstance(event, GroupMessageEvent)

    # ── 无参数：查看状态 ──
    if not parts:
        if is_group:
            await group_voice_cmd.finish(_status_text(event.group_id))
        await group_voice_cmd.finish(_HELP)

    sub = parts[0].lower()

    # ── 设置模式：本群或远程 ──
    mode = group_voice_mode.normalize_mode(sub)
    if mode is not None:
        if len(parts) >= 2:
            # 远程控制指定群（仅超管）
            if not _is_superuser(event.user_id):
                await group_voice_cmd.finish("❌ 仅超级用户可远程控制其他群")
            try:
                target = int(parts[1])
            except ValueError:
                await group_voice_cmd.finish(f"❌ 无效的群号: {parts[1]}")
            if group_voice_mode.set_group_voice_mode(target, mode):
                await group_voice_cmd.finish(
                    f"✅ 已远程设置群 {target} 语音模式：{_mode_label(mode)}"
                )
            await group_voice_cmd.finish("❌ 设置失败，请稍后再试")
        # 本群操作
        if not is_group:
            await group_voice_cmd.finish(
                "❌ 请在本群内使用该命令，或由超管指定群号："
                "/群语音 <模式> <群号>"
            )
        if not _can_manage_group(event):
            await group_voice_cmd.finish("❌ 仅群主/管理员可修改本群语音模式")
        if group_voice_mode.set_group_voice_mode(event.group_id, mode):
            await group_voice_cmd.finish(
                f"✅ 本群语音模式已设置为：{_mode_label(mode)}"
            )
        await group_voice_cmd.finish("❌ 设置失败，请稍后再试")

    # ── reset：本群或远程 ──
    if sub == "reset":
        if len(parts) >= 2:
            # 远程（仅超管）
            if not _is_superuser(event.user_id):
                await group_voice_cmd.finish("❌ 仅超级用户可远程控制其他群")
            try:
                target = int(parts[1])
            except ValueError:
                await group_voice_cmd.finish(f"❌ 无效的群号: {parts[1]}")
            group_voice_mode.reset_group(target)
            await group_voice_cmd.finish(f"✅ 群 {target} 已恢复跟随全局默认")
        # 本群
        if not is_group:
            await group_voice_cmd.finish(
                "❌ 请在本群内使用该命令，或由超管指定群号："
                "/群语音 reset <群号>"
            )
        if not _can_manage_group(event):
            await group_voice_cmd.finish("❌ 仅群主/管理员可修改本群语音模式")
        group_voice_mode.reset_group(event.group_id)
        await group_voice_cmd.finish("✅ 本群已恢复跟随全局默认")

    # ── default：仅超管 ──
    if sub == "default":
        if not _is_superuser(event.user_id):
            await group_voice_cmd.finish("❌ 仅超级用户可修改全局默认")
        if len(parts) < 2:
            await group_voice_cmd.finish(
                "用法：/群语音 default auto|voice|text"
            )
        mode = group_voice_mode.normalize_mode(parts[1])
        if mode is None:
            await group_voice_cmd.finish(
                "❌ 无效模式，可用：auto / voice / text"
            )
        if group_voice_mode.set_default_mode(mode):
            await group_voice_cmd.finish(
                f"✅ 全局默认语音模式已设置为：{_mode_label(mode)}"
            )
        await group_voice_cmd.finish("❌ 设置失败，请稍后再试")

    # ── list：仅超管 ──
    if sub == "list":
        if not _is_superuser(event.user_id):
            await group_voice_cmd.finish("❌ 仅超级用户可查看所有群模式")
        states = group_voice_mode.list_group_modes()
        default = group_voice_mode.get_default_mode()
        if not states:
            await group_voice_cmd.finish(
                f"📋 无显式设置的群（全部跟随全局默认：{_mode_label(default)}）"
            )
        lines = [
            "📋 按群语音模式",
            f"· 全局默认：{_mode_label(default)}",
        ]
        for gid, mode in sorted(states.items()):
            lines.append(f"· 群 {gid}：{_mode_label(mode)}")
        await group_voice_cmd.finish("\n".join(lines))

    await group_voice_cmd.finish(_HELP)
