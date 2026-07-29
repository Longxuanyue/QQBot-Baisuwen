"""
紧迫提醒 —— 检测即将截止的活动/卡池，发送单独提醒。
"""

from __future__ import annotations

from nonebot import logger, get_bot

from .config import plugin_config
from .data_reader import get_urgent_events, format_updated_time
from .renderer import render_urgent_image


async def check_and_push_urgent() -> int:
    """检查紧迫事件并推送。返回实际推送的事件条数（0 表示未推送）。"""
    if not plugin_config.enabled:
        return 0

    urgent = get_urgent_events()
    if not urgent:
        logger.info("[GameNews·紧迫] 无需提醒，无即将截止事件")
        return 0

    updated = format_updated_time()
    logger.info(f"[GameNews·紧迫] 发现 {len(urgent)} 个即将截止事件")

    # 渲染图片
    try:
        image_bytes = await render_urgent_image(urgent, updated=updated)
    except Exception as exc:
        logger.error(f"[GameNews·紧迫] 渲染失败: {exc}")
        return 0

    # 获取推送目标
    targets: list[dict[str, str]] = []
    for gid in plugin_config.target_groups:
        targets.append({"target_type": "group", "target_id": str(gid)})
    for uid in plugin_config.target_users:
        targets.append({"target_type": "user", "target_id": str(uid)})

    # 也读订阅列表
    from .storage import GameStorage
    storage = GameStorage(plugin_config.db_path)
    for sub in storage.get_subscriptions():
        key = (sub["target_type"], sub["target_id"])
        if key not in {(t["target_type"], t["target_id"]) for t in targets}:
            targets.append(dict(sub))

    if not targets:
        logger.info("[GameNews·紧迫] 无推送目标，跳过推送")
        return 0

    # 推送
    try:
        bot = get_bot()
    except ValueError:
        logger.warning("[GameNews·紧迫] 无可用 Bot，跳过推送")
        return 0

    import asyncio
    from nonebot.adapters.onebot.v11 import MessageSegment

    msg = MessageSegment.text("⚠ 即将截止提醒！以下活动/卡池将在48小时内结束：\n") + MessageSegment.image(image_bytes)

    pushed_count = 0
    for t in targets:
        try:
            if t["target_type"] == "group":
                await bot.send_group_msg(group_id=int(t["target_id"]), message=msg)
            else:
                await bot.send_private_msg(user_id=int(t["target_id"]), message=msg)
            pushed_count += 1
            await asyncio.sleep(0.5)
        except Exception as exc:
            logger.error(f"[GameNews·紧迫] 推送失败 {t}: {exc}")

    return pushed_count
