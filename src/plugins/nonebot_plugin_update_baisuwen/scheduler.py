import asyncio
from nonebot_plugin_apscheduler import scheduler
from nonebot import logger
from .config import plugin_config
from .memory_manager import MemoryManager


async def nightly_maintenance():
    """夜间记忆维护：清理、升级、合并、睡眠巩固。
    失败时最多重试 3 次，每次间隔 30 秒。"""
    for attempt in range(3):
        try:
            await MemoryManager.run_maintenance_for_all()
            logger.info("夜间记忆维护完成")
            return
        except Exception as e:
            logger.error(f"记忆维护失败 (attempt {attempt + 1}/3): {e}")
            if attempt < 2:
                await asyncio.sleep(30)
    logger.critical("夜间记忆维护彻底失败，已跳过本次维护")


# 使用配置中的时间创建定时任务
@scheduler.scheduled_job(
    "cron",
    hour=plugin_config.memory_maintenance_hour,
    minute=plugin_config.memory_maintenance_minute,
    id="memory_maintenance"
)
async def scheduled_maintenance():
    await nightly_maintenance()