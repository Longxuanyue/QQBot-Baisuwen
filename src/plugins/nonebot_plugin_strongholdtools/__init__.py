"""
nonebot_plugin_strongholdtools - 明日方舟卫戍协议查询插件

提供敌人信息查询，支持按编号、名称、标签检索。
"""

__version__ = "0.3.0"

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, Message, MessageSegment
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata

from .query import (
    search_by_id,
    search_by_name,
    search_by_tags,
    search_mixed,
)
from .formatter import format_entry_detail, build_name_list_message
from .data_manager import load_data

# ── 插件元数据 ──

__plugin_meta__ = PluginMetadata(
    name="卫戍协议查询",
    description="明日方舟卫戍协议敌人信息查询工具，支持按编号、名称、标签检索",
    usage="发送 /卫戍协议 帮助 查看详细用法；支持单条件查询与混合查询",
    type="application",
    homepage="https://github.com/baisuwen",
    supported_adapters={"~onebot.v11"},
    extra={
        "author": "baisuwen",
        "version": __version__,
    },
)

stronghold = on_command("卫戍协议", priority=5, block=True)


@stronghold.handle()
async def handle_stronghold(bot: Bot, event: MessageEvent, arg: Message = CommandArg()):
    load_data()

    args_text = arg.extract_plain_text().strip()
    if not args_text or args_text == "帮助":
        help_msg = (
            "欢迎使用【明日方舟-卫戍小助手】。您可以输入以下指令来查询相关信息：\n"
            "/卫戍协议 【标签】        - 按标签查询（如：/卫戍协议 飞行）\n"
            "/卫戍协议 【名称】        - 按名称查询（如：/卫戍协议 元核孽生者）\n"
            "/卫戍协议 【编号】        - 按编号查询（如：/卫戍协议 XS001）\n"
            "支持混合查询，多个关键词用空格分隔（如：/卫戍协议 法术大师A2 飞行）\n"
            "注：若标签仅为“悬赏”，因数据量过大将不予返回。"
        )
        await stronghold.finish(help_msg)

    keywords = args_text.split()
    if not keywords:
        await stronghold.finish("请输入查询关键词，或发送 /卫戍协议 帮助 查看用法。")

    if len(keywords) == 1 and keywords[0] == "悬赏":
        await stronghold.finish("数据量过大，无法返回全部悬赏信息，请细化查询条件。")

    # 单关键词
    if len(keywords) == 1:
        kw = keywords[0]

        # ID 查询
        entry = search_by_id(kw)
        if entry:
            text, img_path = format_entry_detail(entry)
            msg_text = f"已为您查询到编号为【{kw}】的信息：\n{text}"
            if img_path and img_path.exists():
                await stronghold.finish(MessageSegment.image(img_path) + MessageSegment.text(f"\n{msg_text}"))
            else:
                await stronghold.finish(msg_text)

        # 名称查询
        entries = search_by_name(kw)
        if len(entries) == 1:
            text, img_path = format_entry_detail(entries[0])
            msg_text = f"已为您查询到名称为【{kw}】的信息：\n{text}"
            if img_path and img_path.exists():
                await stronghold.finish(MessageSegment.image(img_path) + MessageSegment.text(f"\n{msg_text}"))
            else:
                await stronghold.finish(msg_text)
        elif len(entries) > 1:
            msg = f"【{kw}】拥有以下重名信息，请您确认要查询的是哪一位？\n"
            msg += build_name_list_message(entries, kw)
            await stronghold.finish(msg)

        # 标签查询
        entries = search_by_tags([kw])
        if entries:
            msg = build_name_list_message(entries, kw)
            await stronghold.finish(msg)

        await stronghold.finish("对不起，未能查询到对应信息，请您重新输入")

    # 混合查询
    else:
        results = search_mixed(keywords)
        if not results:
            await stronghold.finish("对不起，未能查询到对应信息，请您重新输入")

        if len(results) == 1:
            text, img_path = format_entry_detail(results[0])
            msg_text = f"已为您查询到匹配信息：\n{text}"
            if img_path and img_path.exists():
                await stronghold.finish(MessageSegment.image(img_path) + MessageSegment.text(f"\n{msg_text}"))
            else:
                await stronghold.finish(msg_text)
        else:
            kw_str = " ".join(keywords)
            msg = f"查询条件【{kw_str}】匹配到多个敌人，请确认：\n"
            msg += build_name_list_message(results, kw_str)
            await stronghold.finish(msg)