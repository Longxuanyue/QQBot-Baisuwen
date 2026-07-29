import os
from typing import List, Dict, Optional
from ..nonebot_plugin_memory.user_manager import UserMemoryManager as BaseMemoryManager

class MemoryManager:
    """单例管理器，负责为每个用户创建/获取 UserMemoryManager 实例"""
    _instances = {}

    @classmethod
    def get_manager(cls, user_id: str) -> BaseMemoryManager:
        if user_id not in cls._instances:
            cls._instances[user_id] = BaseMemoryManager(user_id)
        return cls._instances[user_id]

    @classmethod
    def get_all_user_ids(cls) -> List[str]:
        """获取所有有记忆数据的用户ID（通过扫描 user_data 目录）"""
        from .config import plugin_config
        user_data_dir = plugin_config.memory.user_data_dir
        if not os.path.exists(user_data_dir):
            return []
        user_ids = set()
        for f in os.listdir(user_data_dir):
            if f.startswith("short_") and f.endswith(".db"):
                user_id = f[6:-3]
                user_ids.add(user_id)
        return list(user_ids)

    @classmethod
    async def run_maintenance_for_all(cls):
        """对所有用户执行夜间维护（清理、升级、合并、睡眠巩固）。
        单个用户失败不影响其他用户的维护。"""
        from nonebot import logger
        success_count = 0
        fail_count = 0
        for user_id in cls.get_all_user_ids():
            try:
                mgr = cls.get_manager(user_id)
                mgr.cleanup()
                mgr.merge_similar()
                mgr.upgrade_and_deduplicate()
                mgr.sleep_consolidation()
                success_count += 1
            except Exception as e:
                fail_count += 1
                logger.error(f"用户 {user_id} 记忆维护失败: {e}")
            import asyncio
            await asyncio.sleep(0.05)
        if fail_count > 0:
            logger.warning(
                f"夜间记忆维护完成: {success_count} 成功, {fail_count} 失败"
            )