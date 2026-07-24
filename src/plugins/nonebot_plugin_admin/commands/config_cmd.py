"""配置热重载和休眠控制命令"""

from nonebot import logger


async def handle_reload(args: str) -> str:
    """热重载人设或配置"""
    target = args.strip().lower()

    if target == "personality":
        try:
            from ...nonebot_plugin_update_baisuwen.personality import reload_personality
            reload_personality()
            logger.info("人设文件已热重载")
            return "✅ 人设文件已重新加载"
        except Exception as e:
            logger.error(f"人设重载失败: {e}")
            return f"❌ 人设重载失败: {e}"

    elif target == "config":
        try:
            # 重载 .env 配置：重新加载 dotenv + 重建 pydantic config
            from ...nonebot_plugin_update_baisuwen.config import (
                PROJECT_ROOT, plugin_config
            )
            import os as _os
            from dotenv import load_dotenv

            _env_path = _os.path.join(PROJECT_ROOT, ".env")
            if _os.path.exists(_env_path):
                load_dotenv(_env_path, override=True)
                logger.info("环境变量已重新加载")

            # 也重载人设（配置变更可能影响人设加载路径）
            from ...nonebot_plugin_update_baisuwen.personality import reload_personality
            reload_personality()

            logger.info("配置已热重载（部分配置可能需重启才能生效）")
            return "✅ 环境变量已重新加载（部分配置如端口、驱动需重启Bot才能生效）"
        except Exception as e:
            return f"❌ 配置重载失败: {e}"

    else:
        return "请指定重载目标: personality 或 config\n例如: /admin reload personality"


async def handle_sleep_toggle(args: str) -> str:
    """休眠开关"""
    mode = args.strip().lower()

    if mode == "on":
        try:
            from ...nonebot_plugin_update_baisuwen.config import plugin_config
            plugin_config.schedule.bot_sleep_start = "00:00"
            plugin_config.schedule.bot_sleep_end = "23:59"
            return "😴 已强制进入休眠模式"
        except Exception as e:
            return f"❌ 休眠设置失败: {e}"

    elif mode == "off":
        try:
            from ...nonebot_plugin_update_baisuwen.config import plugin_config
            # 恢复默认休眠时段
            plugin_config.schedule.bot_sleep_start = "23:30"
            plugin_config.schedule.bot_sleep_end = "06:00"
            return "☀️ 已退出强制休眠，恢复正常作息"
        except Exception as e:
            return f"❌ 休眠取消失败: {e}"

    else:
        return "请指定 on 或 off\n例如: /admin sleep on"
