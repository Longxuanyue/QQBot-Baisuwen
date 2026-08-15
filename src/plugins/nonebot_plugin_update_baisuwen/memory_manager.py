import os
from typing import List
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

        v2 优化：
        - 跳过没有任何记忆的空库（惰性建库后不应存在，清理历史遗留）
        - 线程池并发执行（上限 8），避免串行阻塞；单个用户失败不影响其他用户
        """
        import asyncio
        from nonebot import logger

        managers = []
        for user_id in cls.get_all_user_ids():
            try:
                mgr = cls.get_manager(user_id)
                if mgr.is_empty():
                    continue
                managers.append(mgr)
            except Exception as e:
                logger.debug(f"检查用户 {user_id} 记忆库失败: {e}")

        if not managers:
            logger.info("夜间记忆维护：无有效记忆用户，跳过")
            return

        sem = asyncio.Semaphore(8)

        async def maintain(mgr: BaseMemoryManager) -> bool:
            async with sem:
                try:
                    await asyncio.to_thread(cls._maintain_one, mgr)
                except Exception as e:
                    logger.error(f"用户 {mgr.user_id} 记忆维护失败: {e}")
                    return False
                return True

        results = await asyncio.gather(*(maintain(m) for m in managers))
        success_count = sum(1 for ok in results if ok)
        fail_count = len(results) - success_count

        # ── 群聊学习库维护（仅清理弱记忆 + 合并相似记忆，不升级） ──
        from .config import plugin_config
        user_data_dir = plugin_config.memory.user_data_dir
        group_dbs = []
        if os.path.isdir(user_data_dir):
            group_dbs = [
                os.path.join(user_data_dir, f)
                for f in sorted(os.listdir(user_data_dir))
                if f.startswith("group_") and f.endswith(".db")
            ]

        async def maintain_group(db_path: str) -> bool:
            async with sem:
                try:
                    await asyncio.to_thread(cls._maintain_group_db, db_path)
                    return True
                except Exception as e:
                    logger.error(f"群库维护失败 {db_path}: {e}")
                    return False

        group_results = await asyncio.gather(
            *(maintain_group(d) for d in group_dbs)
        )
        group_ok = sum(1 for ok in group_results if ok)

        # ── 向量语义检索：为缺向量的记忆批量计算（ENABLE_VECTOR_SEARCH 时） ──
        await cls._vectorize_all()

        if fail_count > 0:
            logger.warning(
                f"夜间记忆维护完成: {success_count} 成功, {fail_count} 失败"
                f" | 群库 {group_ok}/{len(group_dbs)}"
            )
        else:
            logger.info(
                f"夜间记忆维护完成: {success_count} 个用户"
                f" | 群库 {group_ok}/{len(group_dbs)}"
            )

    @classmethod
    def _maintain_one(cls, mgr: BaseMemoryManager) -> None:
        """单用户维护（线程池中执行）"""
        mgr.cleanup()
        mgr.merge_similar()
        mgr.upgrade_and_deduplicate()
        mgr.sleep_consolidation()

    @classmethod
    def _maintain_group_db(cls, db_path: str) -> None:
        """群库维护（线程池中执行）：清理弱记忆 + 合并相似记忆，不做短→长升级"""
        from ..nonebot_plugin_memory.config import SHORT_TERM_MAX
        from ..nonebot_plugin_memory.forgetting import cleanup_memory
        from ..nonebot_plugin_memory.management import merge_similar_in_short_term

        cleanup_memory(db_path, SHORT_TERM_MAX)
        merge_similar_in_short_term(db_path)

    # ── 向量语义检索支持 ──

    @classmethod
    async def _vectorize_all(cls) -> None:
        """为所有记忆库（用户库 + 群库）增量计算向量。

        仅在 ENABLE_VECTOR_SEARCH=true 且模型可用时执行；
        每轮每库上限 200 条，避免维护任务过久。
        """
        import asyncio

        from nonebot import logger

        try:
            from ..nonebot_plugin_memory.embedding import ENABLE_VECTOR_SEARCH
            if not ENABLE_VECTOR_SEARCH:
                return
        except Exception as e:
            logger.debug(f"向量化跳过: {e}")
            return

        from .config import plugin_config

        dbs: set = set()
        for uid in cls.get_all_user_ids():
            try:
                mgr = cls.get_manager(uid)
                if not mgr.is_empty():
                    dbs.add(mgr.short_db)
                    dbs.add(mgr.long_db)
            except Exception:
                continue
        user_data_dir = plugin_config.memory.user_data_dir
        if os.path.isdir(user_data_dir):
            for f in os.listdir(user_data_dir):
                if f.startswith("group_") and f.endswith(".db"):
                    dbs.add(os.path.join(user_data_dir, f))
        if not dbs:
            return

        sem = asyncio.Semaphore(4)

        async def vectorize_one(db_path: str) -> None:
            async with sem:
                try:
                    await asyncio.to_thread(cls._vectorize_db, db_path)
                except Exception as e:
                    logger.debug(f"向量化失败 {db_path}: {e}")

        await asyncio.gather(*(vectorize_one(d) for d in dbs))

    @classmethod
    def _vectorize_db(cls, db_path: str) -> None:
        """单库增量向量化：仅处理缺失向量的记忆（每轮上限 200 条）"""
        import sqlite3

        from ..nonebot_plugin_memory.embedding import store_embedding

        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT m.id, m.content FROM memories m "
                "LEFT JOIN memory_vectors v ON m.id = v.memory_id "
                "WHERE v.memory_id IS NULL LIMIT 200"
            ).fetchall()
        finally:
            conn.close()
        for mem_id, content in rows:
            try:
                store_embedding(db_path, mem_id, content)
            except Exception:
                break  # 模型不可用或失败，停止本轮
