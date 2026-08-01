"""
nonebot_plugin_multimodal - 多模态支持插件

处理图片消息，提供可选的 LLM vision 图片理解能力。
"""

__version__ = "0.2.0"

from nonebot import logger
from nonebot.plugin import PluginMetadata

from .image_handler import (
    download_image,
    extract_image_segments,
    handle_image_message,
    analyze_image_via_llm,
    cleanup_image_cache,
    ENABLE_VISION
)

__all__ = [
    "download_image", "extract_image_segments",
    "handle_image_message", "analyze_image_via_llm",
    "cleanup_image_cache",
    "ENABLE_VISION"
]


# ── 定时清理 image_cache（每日 0:30） ──

try:
    from nonebot_plugin_apscheduler import scheduler

    @scheduler.scheduled_job(
        "cron", hour=0, minute=30,
        id="image_cache_cleanup", misfire_grace_time=300,
    )
    async def scheduled_image_cache_cleanup() -> None:
        """每日 0:30 清理超过 7 天的图片缓存文件。"""
        await cleanup_image_cache(max_age_days=7)

except ImportError:
    logger.warning("apscheduler 未安装，image_cache 自动清理任务不可用")

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
