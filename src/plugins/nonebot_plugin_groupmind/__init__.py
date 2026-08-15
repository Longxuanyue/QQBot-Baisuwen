"""
群聊学习插件（library，无独立命令逻辑；管理命令见 commands.py）

功能：
- 群消息采集（内存缓冲 + 批量写盘，不阻塞消息链路）
- 群统计（活跃时段/话题/昵称/@关系/氛围分）
- 群记忆批量提取与群风格卡（APScheduler 每日低频 LLM 任务）
- 群上下文块构建（供核心插件注入 system prompt）
"""

import asyncio
import os
import time
from typing import List, Optional

from nonebot import get_driver, logger
from nonebot.plugin import PluginMetadata

from . import storage, summarizer
from .config import (
    GROUP_FLUSH_BATCH, GROUP_FLUSH_INTERVAL, GROUP_HISTORY_KEEP,
    GROUP_LEARNING, GROUP_LEARN_DEFAULT, GROUP_MEMORY_EXTRACT_TIMES,
    GROUP_STYLE_CARD_INTERVAL, GROUP_STYLE_CARD_TIME,
)
from .retrieval import build_group_context, format_speaker
from .stats import get_stats, drop_stats

__version__ = "0.1.0"

__plugin_meta__ = PluginMetadata(
    name="群聊学习",
    description="群级记忆、群画像统计、群风格卡与自适应回复概率",
    usage="/群学习 on|off|status|clear|summary",
    type="library",
    homepage="https://github.com/baisuwen",
    supported_adapters={"~onebot.v11"},
    extra={"author": "baisuwen", "version": __version__},
)

# 后台任务引用（防 GC）
_bg_tasks: set = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


class GroupMind:
    """群聊学习门面：event_handler 与命令层只与本类交互"""

    # ── 开关 ──

    @staticmethod
    def global_enabled() -> bool:
        return GROUP_LEARNING

    @staticmethod
    def is_enabled(group_id) -> bool:
        if not GROUP_LEARNING:
            return False
        db_path = storage.group_db_path(group_id)
        if not os.path.exists(db_path):
            return GROUP_LEARN_DEFAULT
        return storage.get_meta(db_path, "enabled", "") == "1"

    # ── 采集 ──

    async def ingest(self, bot, event, msg_text: str) -> None:
        """群消息采集：内存统计 + 缓冲批量写盘。热路径只做内存操作。"""
        if not GROUP_LEARNING:
            return
        gid = event.group_id
        if not self.is_enabled(gid):
            return
        if str(event.user_id) == str(getattr(bot, "self_id", "")):
            return  # 忽略 bot 自己的消息

        mentions = self._extract_mentions(event)
        ts = time.time()
        stats = get_stats(gid)
        stats.ingest(
            str(event.user_id), msg_text, mentions, ts, is_bot=False
        )

        # 攒满一批 → 异步批量写盘
        if len(stats.msg_buffer) >= GROUP_FLUSH_BATCH:
            _spawn(self._flush_one(gid))

    @staticmethod
    def _extract_mentions(event) -> List[str]:
        mentions = []
        try:
            for seg in event.message:
                if seg.type == "at":
                    qq = str(seg.data.get("qq", ""))
                    if qq and qq != "all":
                        mentions.append(qq)
        except Exception:
            pass
        return mentions

    # ── 氛围分与自适应概率 ──

    def note_bot_reply(self, group_id) -> None:
        """记录 bot 回复（开启接话窗口）"""
        if not GROUP_LEARNING:
            return
        try:
            get_stats(group_id).note_bot_reply()
        except Exception:
            pass

    def get_adaptive_factor(self, group_id) -> float:
        """自适应概率系数（未开启学习时恒为 1.0）"""
        if not GROUP_LEARNING:
            return 1.0
        try:
            return get_stats(group_id).get_adaptive_factor()
        except Exception:
            return 1.0

    # ── 上下文 ──

    def build_group_context(self, group_id, msg_text: str) -> str:
        if not self.is_enabled(group_id):
            return ""
        try:
            return build_group_context(group_id, msg_text)
        except Exception as e:
            logger.debug(f"群上下文构建失败: {e}")
            return ""

    def format_speaker(self, group_id, user_id: str) -> str:
        try:
            return format_speaker(group_id, user_id)
        except Exception:
            return str(user_id)

    # ── LLM 批量任务（供 APScheduler 与命令调用） ──

    async def extract_group_memories(self, group_id) -> int:
        if not self.is_enabled(group_id):
            return 0
        try:
            from ..nonebot_plugin_update_baisuwen.config import plugin_config
            from ..nonebot_plugin_update_baisuwen.llm_client import llm_client
            return await summarizer.extract_group_memories(
                group_id, llm_client, plugin_config
            )
        except Exception as e:
            logger.debug(f"群记忆提取调度失败: {e}")
            return 0

    async def generate_style_card(self, group_id) -> Optional[str]:
        if not self.is_enabled(group_id):
            return None
        try:
            from ..nonebot_plugin_update_baisuwen.config import plugin_config
            from ..nonebot_plugin_update_baisuwen.llm_client import llm_client
            return await summarizer.generate_style_card(
                group_id, llm_client, plugin_config
            )
        except Exception as e:
            logger.debug(f"群风格卡调度失败: {e}")
            return None

    # ── 数据查询（命令 / WebUI 使用） ──

    def list_group_ids(self) -> List[str]:
        """所有存在群库的群 id"""
        return storage.list_group_ids()

    def get_group_stats(self, group_id) -> dict:
        return storage.get_group_stats(storage.group_db_path(group_id))

    def list_group_memories(self, group_id, limit: int = 100) -> List[dict]:
        return storage.get_group_memories(
            storage.group_db_path(group_id), limit
        )

    def delete_group_memory(self, group_id, memory_id) -> bool:
        return storage.delete_group_memory(
            storage.group_db_path(group_id), memory_id
        )

    def clear_group_data(self, group_id) -> int:
        n = storage.clear_group_data(storage.group_db_path(group_id))
        drop_stats(group_id)
        return n

    # ── 内部：批量写盘 ──

    async def _flush_one(self, group_id) -> None:
        try:
            stats = get_stats(group_id)
            db_path = storage.group_db_path(group_id)
            if not os.path.exists(db_path):
                os.makedirs(os.path.dirname(db_path), exist_ok=True)
                storage.init_group_database(db_path)
            written = await asyncio.to_thread(stats.flush, storage, db_path)
            # 按消息数触发风格卡
            if written > 0:
                cnt_key = "msgs_since_style"
                total = int(storage.get_meta(db_path, cnt_key, "0") or "0") + written
                if total >= GROUP_STYLE_CARD_INTERVAL:
                    storage.set_meta(db_path, cnt_key, "0")
                    _spawn(self.generate_style_card(group_id))
                else:
                    storage.set_meta(db_path, cnt_key, str(total))
        except Exception as e:
            logger.debug(f"群数据写盘失败 [{group_id}]: {e}")

    async def flush_all(self) -> None:
        """兜底刷新所有群的内存缓冲（APScheduler 周期调用）"""
        if not GROUP_LEARNING:
            return
        for gid in sorted(
            set(storage.list_group_ids()) | set(_stats_cache_keys())
        ):
            await self._flush_one(gid)

    # ── 维护 ──

    async def daily_maintenance(self) -> None:
        """每日维护：清理消息流水 + 惰性氛围衰减 + 动态词典学习"""
        if not GROUP_LEARNING:
            return
        for gid in storage.list_group_ids():
            db_path = storage.group_db_path(gid)
            try:
                pruned = await asyncio.to_thread(
                    storage.prune_messages, db_path, GROUP_HISTORY_KEEP
                )
                if pruned:
                    logger.info(f"群消息流水清理 [{gid}]: 删除 {pruned} 条")
                get_stats(gid).decay_atmosphere()
            except Exception as e:
                logger.debug(f"群维护失败 [{gid}]: {e}")
        await self.learn_dynamic_words()

    async def learn_dynamic_words(self) -> int:
        """动态词典学习：相邻词共现 → 新词加入全局 jieba 词典（每日上限 10 个）。

        原理：若"明日"与"方舟"频繁相邻出现（共现 >= 5），说明 jieba 把它们
        切错了，合并为"明日方舟"加入词典，次日分词即正确。
        """
        from collections import defaultdict

        from ..nonebot_plugin_memory.text_utils import (
            DYNAMIC_DICT_PATH, add_dynamic_word, tokenize,
        )
        try:
            known = set()
            if os.path.exists(DYNAMIC_DICT_PATH):
                with open(DYNAMIC_DICT_PATH, "r", encoding="utf-8") as f:
                    for line in f:
                        w = line.strip().split()
                        if w:
                            known.add(w[0])
        except Exception:
            known = set()

        learned = 0
        for gid in storage.list_group_ids():
            if not self.is_enabled(gid) or learned >= 10:
                continue
            db_path = storage.group_db_path(gid)
            msgs = storage.get_recent_messages(db_path, 200)
            if len(msgs) < 20:
                continue
            freq: dict = defaultdict(int)
            cooc: dict = defaultdict(int)
            for m in msgs:
                words = tokenize(m["content"])
                for w in words:
                    freq[w] += 1
                for i in range(len(words) - 1):
                    cooc[(words[i], words[i + 1])] += 1
            for (a, b), c in sorted(cooc.items(), key=lambda x: -x[1]):
                if learned >= 10:
                    break
                cand = a + b
                if len(cand) < 2 or len(cand) > 8 or cand in known:
                    continue
                if c >= 5 and freq.get(a, 0) >= 3 and freq.get(b, 0) >= 3:
                    if add_dynamic_word(cand):
                        known.add(cand)
                        learned += 1
                        logger.info(f"动态词典学习新词: {cand} (共现 {c} 次)")
        if learned:
            logger.info(f"动态词典学习完成: 新增 {learned} 个词")
        return learned


def _stats_cache_keys() -> List[str]:
    """当前内存中的统计键（供 flush_all 使用）"""
    from .stats import all_group_keys
    return all_group_keys()


# 全局单例
groupmind = GroupMind()


# ── APScheduler 任务注册 ──

def _parse_hhmm(value: str) -> tuple:
    try:
        h, m = value.strip().split(":")
        return int(h), int(m)
    except (ValueError, AttributeError):
        return 21, 0


def register_scheduler() -> None:
    """注册定时任务（仅全局开关开启时）"""
    if not GROUP_LEARNING:
        return
    try:
        from nonebot_plugin_apscheduler import scheduler

        # 缓冲兜底刷新
        scheduler.add_job(
            groupmind.flush_all, "interval",
            seconds=GROUP_FLUSH_INTERVAL, id="groupmind_flush",
            max_instances=1, coalesce=True,
        )
        # 每日维护（消息流水清理 + 氛围衰减）
        scheduler.add_job(
            groupmind.daily_maintenance, "cron",
            hour=3, minute=0, id="groupmind_daily",
            max_instances=1, coalesce=True,
        )
        # 群记忆批量提取（每日多次）
        for i, t in enumerate(GROUP_MEMORY_EXTRACT_TIMES.split(",")):
            h, m = _parse_hhmm(t)
            scheduler.add_job(
                run_extract_all, "cron",
                hour=h, minute=m, id=f"groupmind_extract_{i}",
                max_instances=1, coalesce=True,
            )
        # 群风格卡（每日一次）
        h, m = _parse_hhmm(GROUP_STYLE_CARD_TIME)
        scheduler.add_job(
            run_style_all, "cron",
            hour=h, minute=m, id="groupmind_style",
            max_instances=1, coalesce=True,
        )
        logger.info("群聊学习定时任务已注册")
    except Exception as e:
        logger.debug(f"群聊学习定时任务注册失败: {e}")


async def run_extract_all() -> None:
    """批量执行所有启用群的群记忆提取（APScheduler）"""
    if not GROUP_LEARNING:
        return
    for gid in storage.list_group_ids():
        if groupmind.is_enabled(gid):
            await groupmind.extract_group_memories(gid)


async def run_style_all() -> None:
    """批量生成所有启用群的风格卡（APScheduler）"""
    if not GROUP_LEARNING:
        return
    for gid in storage.list_group_ids():
        if groupmind.is_enabled(gid):
            await groupmind.generate_style_card(gid)


# ── 启动钩子 ──

driver = get_driver()


@driver.on_startup
async def _on_startup() -> None:
    register_scheduler()
