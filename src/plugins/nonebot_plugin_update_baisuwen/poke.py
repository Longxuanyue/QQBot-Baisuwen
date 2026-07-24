import random
from nonebot import on_notice
from nonebot.adapters.onebot.v11 import Bot, PokeNotifyEvent
from nonebot.rule import Rule

def is_poke_event(event: PokeNotifyEvent) -> bool:
    """判断是否为戳一戳事件，并且被戳的是机器人自己"""
    return event.notice_type == "notify" and event.sub_type == "poke" and event.is_tome()

# 提高优先级到 1，并设置 block=True 确保处理后不再传播
poke_matcher = on_notice(rule=is_poke_event, priority=1, block=True)

@poke_matcher.handle()
async def handle_poke(bot: Bot, event: PokeNotifyEvent):
    await poke_matcher.send("嗷呜？你要干嘛？")
    # 无论哪种分支，都结束事件处理，防止被其他插件再次响应
    await poke_matcher.finish()