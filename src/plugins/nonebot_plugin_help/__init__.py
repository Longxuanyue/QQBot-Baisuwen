"""
nonebot_plugin_help - 统一指令帮助插件

提供 /help 和 /帮助 命令，汇总所有已加载插件的可用指令。
按类别分组展示，支持查询特定插件的详细指令。
"""

__version__ = "0.3.0"

from nonebot import on_command, logger
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, Message
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata

from .collector import collect_commands, find_plugin_commands

# ── 插件元数据 ──

__plugin_meta__ = PluginMetadata(
    name="指令帮助",
    description="统一指令帮助 — 汇总所有已加载插件的可用指令，支持分类浏览和插件详情查询",
    usage="发送 /help 查看全部指令索引；/help <插件名> 查看特定插件详情",
    type="application",
    homepage="https://github.com/baisuwen",
    supported_adapters={"~onebot.v11"},
    extra={
        "author": "baisuwen",
        "version": __version__,
    },
)

# ── 命令注册 ──

help_cmd = on_command("help", aliases={"帮助"}, priority=1, block=True)


@help_cmd.handle()
async def handle_help(bot: Bot, event: MessageEvent, arg: Message = CommandArg()):
    args_text = arg.extract_plain_text().strip()

    if args_text:
        # 查询特定插件
        msg = _format_plugin_detail(args_text)
    else:
        # 总索引
        msg = _format_overview()

    await help_cmd.finish(msg)


# ── 格式化函数 ──

def _format_overview() -> str:
    """格式化所有插件的指令总索引，按类别分组。"""
    plugins = collect_commands()

    if not plugins:
        return "当前没有已加载的插件，或插件尚未完全初始化。请稍后再试~"

    # 过滤出有指令的插件
    cmd_plugins = [p for p in plugins if p["has_commands"]]
    # 库插件（无用户指令）单独列出
    lib_plugins = [p for p in plugins if not p["has_commands"]]

    lines = ["📋 白苏文 Bot 指令总览", "=" * 30]

    # 按类别分组
    current_category = None
    for p in cmd_plugins:
        cat = p["category_label"]
        if cat != current_category:
            current_category = cat
            lines.append(f"\n{cat}")

        # 插件标题
        lines.append(f"  📌 {p['plugin_name']} ({p['plugin_id']})")
        if p["description"]:
            lines.append(f"     {p['description']}")

        # 指令列表（最多显示前 6 条）
        shown = p["commands"][:6]
        for cmd in shown:
            name = cmd["name"]
            desc = cmd.get("desc", "")
            if len(name) > 28:
                lines.append(f"     • {name}")
                if desc:
                    lines.append(f"       {desc}")
            else:
                lines.append(f"     • {name:<28} {desc}")

        short_name = p['plugin_id'].replace('nonebot_plugin_', '')
        if len(p["commands"]) > 6:
            lines.append(f"     … 还有 {len(p['commands']) - 6} 条指令")
        lines.append(f"     🔍 /help {short_name} 查看详情")

    # 底部提示
    lines.append(f"\n{'─' * 30}")
    lines.append("💡 输入 /help <插件名> 查看插件详细指令")
    lines.append("💡 插件名可简写，如 /help skland、/help admin")

    if lib_plugins:
        lib_names = [p["plugin_name"] for p in lib_plugins]
        lines.append(f"\n📚 底层库插件（无直接用户指令）: {', '.join(lib_names)}")

    return "\n".join(lines)


def _format_plugin_detail(query: str) -> str:
    """格式化特定插件的详细指令。"""
    plugin = find_plugin_commands(query)

    if not plugin:
        return (
            f"❌ 未找到匹配的插件: {query}\n\n"
            f"请输入 /help 查看所有可用插件的列表。\n"
            f"提示：插件名可简写（如 skland、admin、status）"
        )

    lines = [
        f"📌 {plugin['plugin_name']}",
        f"插件标识: {plugin['plugin_id']}",
    ]

    if plugin["description"]:
        lines.append(f"简介: {plugin['description']}")
    if plugin["usage"]:
        lines.append(f"用法: {plugin['usage']}")

    lines.append(f"分类: {plugin['category_label']}")
    lines.append(f"{'─' * 30}")

    if plugin["commands"]:
        lines.append("可用指令:")
        for i, cmd in enumerate(plugin["commands"], 1):
            name = cmd["name"]
            desc = cmd.get("desc", "")
            lines.append(f"  {i:>2}. {name}")
            if desc:
                lines.append(f"      {desc}")
    else:
        lines.append("该插件未提供详细指令列表。")

    lines.append(f"\n{'─' * 30}")
    lines.append("💡 输入 /help 返回总索引")

    return "\n".join(lines)
