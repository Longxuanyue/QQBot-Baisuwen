"""
nonebot_plugin_sentiment - 情感分析插件

识别用户消息中的情绪，调整机器人回复策略。
"""

__version__ = "0.1.0"

from nonebot.plugin import PluginMetadata

from .analyzer import SentimentAnalyzer, sentiment_analyzer

__all__ = ["SentimentAnalyzer", "sentiment_analyzer"]

# ── 插件元数据 ──

__plugin_meta__ = PluginMetadata(
    name="情感分析",
    description="识别用户消息中的情绪，调整机器人回复策略，支持 LLM 和规则两种模式",
    usage="内部 library 插件，无直接用户命令；为其他插件提供情感分析能力",
    type="library",
    homepage="https://github.com/baisuwen",
    supported_adapters={"~onebot.v11"},
    extra={
        "author": "baisuwen",
        "version": __version__,
    },
)
