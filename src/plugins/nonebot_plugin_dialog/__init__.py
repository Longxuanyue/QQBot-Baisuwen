"""
nonebot_plugin_dialog - 多轮对话管理插件

提供有状态的对话上下文管理（会话级历史、话题追踪、TTL 过期清理）。
"""

__version__ = "0.1.0"

from nonebot.plugin import PluginMetadata

from .manager import DialogManager, DialogSession, dialog_manager

__all__ = ["DialogManager", "DialogSession", "dialog_manager"]

# ── 插件元数据 ──

__plugin_meta__ = PluginMetadata(
    name="对话管理",
    description="多轮对话上下文管理，提供会话级历史、话题追踪、TTL 过期自动清理",
    usage="内部 library 插件，无直接用户命令；为其他插件提供对话管理能力",
    type="library",
    homepage="https://github.com/baisuwen",
    supported_adapters={"~onebot.v11"},
    extra={
        "author": "baisuwen",
        "version": __version__,
    },
)
