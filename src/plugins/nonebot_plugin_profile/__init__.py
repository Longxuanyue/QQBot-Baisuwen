"""
nonebot_plugin_profile - 用户画像系统

从记忆库自动提取用户特征，构建结构化画像。
"""

__version__ = "0.1.0"

from nonebot.plugin import PluginMetadata

from .profiler import UserProfiler, profiler

__all__ = ["UserProfiler", "profiler"]

# ── 插件元数据 ──

__plugin_meta__ = PluginMetadata(
    name="用户画像",
    description="从记忆库自动提取用户特征，构建结构化用户画像",
    usage="内部 library 插件，无直接用户命令；为其他插件提供用户画像能力",
    type="library",
    homepage="https://github.com/baisuwen",
    supported_adapters={"~onebot.v11"},
    extra={
        "author": "baisuwen",
        "version": __version__,
    },
)
