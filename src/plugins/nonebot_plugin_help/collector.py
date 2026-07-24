"""
命令收集器：从所有已加载插件中收集指令信息。

支持两种指令系统：
1. 原生 Nonebot2 指令（on_command）—— 通过 PluginMetadata.extra["commands"] 获取
2. Alconna 指令（on_alconna）—— 通过 command_manager.get_commands() 获取
"""

from typing import List, Dict, Any, Optional
from nonebot import get_loaded_plugins, get_driver, logger


# ── 已知插件指令的手动映射（作为元数据缺失时的后备） ──

_KNOWN_COMMANDS: Dict[str, List[Dict[str, str]]] = {
    "nonebot_plugin_admin": [
        {"name": "/admin", "desc": "管理员命令面板（仅主人可用）"},
        {"name": "/admin status", "desc": "查看 Bot 服务状态"},
        {"name": "/admin memory <uid>", "desc": "查看用户的记忆统计"},
        {"name": "/admin reload [personality|config]", "desc": "热重载人设或配置"},
        {"name": "/admin sleep [on|off]", "desc": "切换 Bot 休眠状态"},
    ],
    "nonebot_plugin_strongholdtools": [
        {"name": "/卫戍协议", "desc": "明日方舟卫戍协议查询 — 显示帮助信息"},
        {"name": "/卫戍协议 <编号>", "desc": "按编号查询（如 XS001）"},
        {"name": "/卫戍协议 <名称>", "desc": "按敌人名称查询"},
        {"name": "/卫戍协议 <标签>", "desc": "按标签查询（如 飞行、悬赏等）"},
    ],
    "nonebot_plugin_webui": [
        {"name": "/auth <token>", "desc": "WebUI 管理后台登录验证"},
    ],
    "nonebot_plugin_help": [
        {"name": "/help", "desc": "查看所有可用指令的总索引"},
        {"name": "/help <插件名>", "desc": "查看指定插件的详细指令"},
        {"name": "/帮助", "desc": "同 /help（中文别名）"},
    ],
    "nonebot_plugin_gamenews": [
        {"name": "/游戏新闻 [游戏名]", "desc": "查看全部/指定游戏的活动进度（图片）"},
        {"name": "/卡池 [游戏名]", "desc": "查看全部/指定游戏的当期卡池（图片）"},
        {"name": "/活动 [游戏名]", "desc": "查看全部/指定游戏的进行中活动（图片）"},
        {"name": "/紧急活动", "desc": "查看 48h 内即将截止的活动/卡池"},
        {"name": "/订阅新闻", "desc": "订阅每日活动推送（含紧迫提醒）"},
        {"name": "/取消新闻", "desc": "取消订阅每日推送"},
        {"name": "/游戏新闻状态", "desc": "查看数据更新状态与各游戏覆盖统计"},
        {"name": "/强制更新新闻", "desc": "手动触发数据爬取更新（仅主人）"},
    ],
    "nonebot_plugin_update_baisuwen": [
        {"name": "/voicemode <auto|always|text>", "desc": "切换语音回复模式（仅私聊可用）"},
        {"name": "（对话即响应）", "desc": "Bot 主对话管线 — 直接发消息即可触发 AI 回复"},
        {"name": "（戳一戳）", "desc": "在 QQ 中戳 Bot 会有随机反应"},
    ],
}

# 商店插件的已知指令
_STORE_COMMANDS: Dict[str, List[Dict[str, str]]] = {
    "nonebot_plugin_skland": [
        {"name": "/skland", "desc": "森空岛主命令 — 查看帮助"},
        {"name": "/skland bind", "desc": "绑定森空岛账号（Token / 二维码）"},
        {"name": "/skland unbind", "desc": "解绑森空岛账号"},
        {"name": "/skland card", "desc": "查询角色卡"},
        {"name": "/skland sign", "desc": "每日签到（明日方舟 + 终末地）"},
        {"name": "/skland sign -s", "desc": "查看签到状态"},
        {"name": "/skland gacha", "desc": "抽卡记录查询与分析"},
        {"name": "/skland rogue", "desc": "集成战略（肉鸽）数据查询"},
        {"name": "/skland qrcode", "desc": "获取登录二维码"},
        {"name": "", "desc": "💡 森空岛插件详细相关指令集请输入 /skland --help 查询"},
    ],
    "nonebot_plugin_status": [
        {"name": "/status 或 /状态", "desc": "查看 Bot 服务器状态"},
    ],
    "nonebot_plugin_waiter": [
        {"name": "（库插件，无直接指令）", "desc": "为其他插件提供多轮交互等待功能"},
    ],
}


# ── 插件类别（用于 /help 分组展示） ──

CATEGORY_LABELS = {
    "core": "🧠 核心功能",
    "admin": "🔧 管理工具",
    "game": "🎮 游戏数据",
    "tool": "🛠️ 实用工具",
    "feature": "✨ 功能插件",
    "library": "📚 底层库",
    "application": "📱 应用插件",
}


def collect_commands() -> List[Dict[str, Any]]:
    """收集所有已加载插件的指令信息。

    返回列表，每项格式：
    {
        "plugin_id": str,        # 插件标识符（如 nonebot_plugin_skland）
        "plugin_name": str,      # 显示名称（从 PluginMetadata 读取）
        "description": str,      # 插件简介
        "usage": str,            # 插件用法概览
        "type": str,             # 插件类型（core/admin/game/tool/feature/library/application）
        "category_label": str,   # 分类显示标签
        "commands": list,        # [{"name": str, "desc": str, "source": str}]
        "matcher_types": list,   # 该插件定义的 matcher 类型列表
        "has_commands": bool,    # 是否有可用指令
    }
    """
    plugins = get_loaded_plugins()
    result = []

    # 尝试导入 Alconna 命令管理器
    try:
        from arclet.alconna import command_manager as alc_cmd_mgr
        _has_alconna = True
    except ImportError:
        _has_alconna = False

    # 构建 Alconna 命令 → 插件的映射
    alconna_plugin_map: Dict[str, List[Dict[str, str]]] = {}
    if _has_alconna:
        try:
            from nonebot_plugin_alconna.uniseg import referent
            for cmd in alc_cmd_mgr.get_commands():
                try:
                    ref = referent(cmd)
                    if ref and ref.matcher and ref.matcher.plugin_id:
                        pid = ref.matcher.plugin_id
                        if pid not in alconna_plugin_map:
                            alconna_plugin_map[pid] = []
                        alconna_plugin_map[pid].append({
                            "name": cmd.header_display,
                            "desc": cmd.meta.description or "",
                            "source": "alconna",
                        })
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"Help: Alconna 命令枚举失败: {e}")

    for plugin in plugins:
        # 跳过子插件和内置插件
        if plugin.parent_plugin is not None:
            continue
        if plugin.id_ == "echo":
            continue

        plugin_id = plugin.id_
        plugin_name = plugin.name
        description = ""
        usage = ""
        plugin_type = "feature"

        # 从 PluginMetadata 读取（兼容 dict 和 PluginMetadata 对象）
        if plugin.metadata:
            if isinstance(plugin.metadata, dict):
                # 自定义插件用 __plugin_meta__ dict 定义的元数据
                plugin_name = plugin.metadata.get("name", plugin_name)
                description = plugin.metadata.get("description", "")
                usage = plugin.metadata.get("usage", "")
                plugin_type = plugin.metadata.get("type", plugin_type)
            else:
                # 官方 PluginMetadata 对象
                plugin_name = plugin.metadata.name or plugin_name
                description = plugin.metadata.description or ""
                usage = plugin.metadata.usage or ""
                plugin_type = plugin.metadata.type or plugin_type

        # 收集指令
        commands = []

        # 1. 从已知指令映射获取（优先级最高，因为包含手动整理的完整信息）
        known = _KNOWN_COMMANDS.get(plugin_id, [])
        if not known:
            known = _STORE_COMMANDS.get(plugin_id, [])
        for kc in known:
            commands.append({**kc, "source": "manual"})

        # 2. 从 PluginMetadata.extra["commands"] 获取（兼容 dict 和对象）
        if plugin.metadata:
            extra = plugin.metadata.get("extra", {}) if isinstance(plugin.metadata, dict) else plugin.metadata.extra
            if extra:
                extra_cmds = extra.get("commands", [])
                for ec in extra_cmds:
                    if isinstance(ec, dict):
                        commands.append({
                            "name": ec.get("name", ""),
                            "desc": ec.get("description", ec.get("desc", "")),
                            "source": "metadata",
                        })

        # 3. 从 Alconna 获取
        if plugin_id in alconna_plugin_map:
            for ac in alconna_plugin_map[plugin_id]:
                # 避免重复（如果已知映射中已经有同名指令）
                if not any(c["name"] == ac["name"] for c in commands):
                    commands.append(ac)

        # matcher 类型统计
        matcher_types = list(set(
            m.type for m in plugin.matcher if m.type
        ))

        has_commands = len(commands) > 0 or "command" in matcher_types

        # 即使没有显式指令，但有 command 类型 matcher，也添加占位
        if not commands and "command" in matcher_types:
            commands.append({
                "name": f"（{plugin_name} 的指令）",
                "desc": f"该插件定义了指令但未提供详细帮助，请输入指令名称尝试",
                "source": "auto",
            })

        result.append({
            "plugin_id": plugin_id,
            "plugin_name": plugin_name,
            "description": description,
            "usage": usage,
            "type": plugin_type,
            "category_label": CATEGORY_LABELS.get(plugin_type, "✨ 功能插件"),
            "commands": commands,
            "matcher_types": matcher_types,
            "has_commands": has_commands,
        })

    # 按类别排序：core → admin → feature → game → tool → application → library
    type_order = {
        "core": 0, "admin": 1, "feature": 2, "game": 3,
        "tool": 4, "application": 5, "library": 6,
    }
    result.sort(key=lambda p: (type_order.get(p["type"], 9), p["plugin_id"]))

    return result


def find_plugin_commands(plugin_name: str) -> Optional[Dict[str, Any]]:
    """按插件标识符或显示名称查找插件的指令信息。"""
    all_plugins = collect_commands()
    plugin_name_lower = plugin_name.lower()

    for p in all_plugins:
        if (plugin_name_lower == p["plugin_id"].lower()
                or plugin_name_lower in p["plugin_id"].lower()
                or plugin_name_lower == p["plugin_name"].lower()):
            return p

    # 模糊匹配
    for p in all_plugins:
        pid_simple = p["plugin_id"].replace("nonebot_plugin_", "").replace("nonebot_", "")
        if plugin_name_lower in pid_simple.lower():
            return p

    return None
