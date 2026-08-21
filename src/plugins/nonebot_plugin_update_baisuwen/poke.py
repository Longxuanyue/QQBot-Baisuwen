from nonebot import logger, on_notice
from nonebot.adapters.onebot.v11 import PokeNotifyEvent

from .group_response import is_group_enabled


def is_poke_event(event: PokeNotifyEvent) -> bool:
    """判断是否为戳一戳事件，并且被戳的是机器人自己"""
    return (
        event.notice_type == "notify"
        and event.sub_type == "poke"
        and event.is_tome()
    )


# 提高优先级到 1，并设置 block=True 确保处理后不再传播
poke_matcher = on_notice(rule=is_poke_event, priority=1, block=True)


@poke_matcher.handle()
async def handle_poke(event: PokeNotifyEvent):
    # 按群响应开关：关闭响应的群不响应戳一戳
    group_id = getattr(event, "group_id", None)
    if group_id is not None and not is_group_enabled(group_id):
        logger.info(f"群 {group_id} 已关闭响应，忽略戳一戳")
        return
    await poke_matcher.send("嗷呜？你要干嘛？")
    # 无论哪种分支，都结束事件处理，防止被其他插件再次响应
    await poke_matcher.finish()
