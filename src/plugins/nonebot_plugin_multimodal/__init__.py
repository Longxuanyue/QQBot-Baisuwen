"""
nonebot_plugin_multimodal - 多模态支持插件

处理图片消息，提供可选的 LLM vision 图片理解能力。
"""

__version__ = "0.1.0"

from nonebot.plugin import PluginMetadata

from .image_handler import (
    download_image,
    extract_image_segments,
    handle_image_message,
    analyze_image_via_llm,
    ENABLE_VISION
)

__all__ = [
    "download_image", "extract_image_segments",
    "handle_image_message", "analyze_image_via_llm",
    "ENABLE_VISION"
]

# ── 插件元数据 ──

__plugin_meta__ = PluginMetadata(
    name="多模态支持",
    description="处理图片消息，提供可选的 LLM vision 图片理解能力",
    usage="内部 library 插件，无直接用户命令；为其他插件提供多模态处理能力",
    type="library",
    homepage="https://github.com/baisuwen",
    supported_adapters={"~onebot.v11"},
    extra={
        "author": "baisuwen",
        "version": __version__,
    },
)
