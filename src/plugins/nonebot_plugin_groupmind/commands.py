"""
群聊学习管理命令：/群学习 on|off|status|clear|summary
"""

import json
import os
from typing import Optional

from nonebot import get_driver, on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

from . import storage
from .config import GROUP_LEARNING, GROUP_LEARN_DEFAULT

group_learn = on_command(
    "群学习", aliases={"群学习"}, priority=5, block=True,
)


def _is_superuser(user_id: str) -> bool:
    driver = get_driver()
    return str(user_id) in driver.config.superusers


def _can_manage(event: GroupMessageEvent) -> bool:
    """群主/管理员/超管可管理本群学习开关"""
    if event.sender and event.sender.role in ("owner", "admin"):
        return True
    return _is_superuser(str(event.user_id))


def _get_enabled(group_id) -> bool:
    db_path = storage.group_db_path(group_id)
    if not os.path.exists(db_path):
        return GROUP_LEARN_DEFAULT
    val = storage.get_meta(db_path, "enabled", "")
    if val == "":
        return GROUP_LEARN_DEFAULT
    return val == "1"


def set_enabled(group_id, enabled: bool) -> None:
    """设置群学习开关（建库并写入 meta）"""
    db_path = storage.group_db_path(group_id)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    storage.init_group_database(db_path)
    storage.set_meta(db_path, "enabled", "1" if enabled else "0")


@group_learn.handle()
async def handle_group_learn(
    bot, event: MessageEvent, arg: Optional[str] = None,
):
    arg = (arg or "").strip().lower() if arg else ""

    if not isinstance(event, GroupMessageEvent):
        await group_learn.finish("该命令仅限群聊使用")
        return

    gid = event.group_id

    if not arg:
        enabled = _get_enabled(gid)
        global_state = (
            "✅ 开" if GROUP_LEARNING else "❌ 关（需 GROUP_LEARNING=true）"
        )
        await group_learn.finish(
            "📖 群聊学习\n"
            f"· 本群状态：{'✅ 已开启' if enabled else '❌ 未开启'}\n"
            f"· 全局开关：{global_state}\n"
            "· 命令：/群学习 on|off|status|clear|summary"
        )
        return

    if arg in ("on", "off"):
        if not _can_manage(event):
            await group_learn.finish("❌ 仅群主/管理员可修改学习开关")
            return
        if not GROUP_LEARNING and arg == "on":
            await group_learn.finish(
                "❌ 全局开关 GROUP_LEARNING=false 未开启，"
                "请联系主人修改 .env 后重启"
            )
            return
        set_enabled(gid, arg == "on")
        await group_learn.finish(
            f"✅ 本群群聊学习已{'开启' if arg == 'on' else '关闭'}"
        )
        return

    if arg == "status":
        enabled = _get_enabled(gid)
        db_path = storage.group_db_path(gid)
        stats = storage.get_group_stats(db_path)
        lines = [
            f"📊 群聊学习状态（群 {gid}）",
            f"· 开关：{'✅ 开' if enabled else '❌ 关'}",
        ]
        if stats:
            lines.append(f"· 群记忆：{stats.get('memory_count', 0)} 条")
            lines.append(f"· 消息流水：{stats.get('message_count', 0)} 条")
            lines.append(f"· 活跃成员：{stats.get('member_count', 0)} 人")
            if stats.get("topics"):
                lines.append(f"· 高频话题：{'、'.join(stats['topics'])}")
            if stats.get("active_hours"):
                hours = "、".join(f"{h}点" for h in stats["active_hours"])
                lines.append(f"· 活跃时段：{hours}")
            if stats.get("style_card"):
                try:
                    card = json.loads(stats["style_card"])
                    lines.append(f"· 风格卡：{card.get('tone', '')}")
                except Exception:
                    pass
        await group_learn.finish("\n".join(lines))
        return

    if arg == "clear":
        if not _can_manage(event):
            await group_learn.finish("❌ 仅群主/管理员可清空学习数据")
            return
        db_path = storage.group_db_path(gid)
        deleted = storage.clear_group_data(db_path)
        try:
            from .stats import drop_stats
            drop_stats(gid)
        except Exception:
            pass
        await group_learn.finish(
            f"🗑️ 本群学习数据已清空（删除 {deleted} 条群记忆）"
        )
        return

    if arg == "summary":
        if not _is_superuser(str(event.user_id)):
            await group_learn.finish("❌ 仅超级用户可手动触发总结")
            return
        from .__init__ import groupmind
        await group_learn.send("⏳ 正在提取群记忆与生成风格卡...")
        n = await groupmind.extract_group_memories(gid)
        card = await groupmind.generate_style_card(gid)
        await group_learn.finish(
            f"✅ 群记忆新增 {n} 条；"
            f"风格卡{'已生成' if card else '未生成（消息量不足或失败）'}"
        )
        return

    await group_learn.finish(
        "用法：/群学习 on|off|status|clear|summary"
    )
