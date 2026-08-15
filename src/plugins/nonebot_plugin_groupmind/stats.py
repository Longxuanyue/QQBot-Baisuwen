"""
群聊统计层：纯规则、零 LLM 成本。

- 活跃时段 / 话题词频 / 成员计数 / @ 关系：先在内存累积，flush 时批量写库
- 氛围分：bot 回复后窗口期内是否有人接话 → 指数调整，供自适应回复概率使用
"""

import re
import time
from collections import defaultdict

from .config import (
    GROUP_ATMOSPHERE_BOOST, GROUP_ATMOSPHERE_DECAY,
    GROUP_ATMOSPHERE_MIN, GROUP_ATMOSPHERE_MAX, GROUP_ATMOSPHERE_WINDOW,
)

# 停用词（与 profiler 保持一致并补充群聊常用词）
_STOPWORDS = {
    "我", "你", "他", "她", "它", "的", "了", "是", "在", "和", "就", "都",
    "也", "很", "要", "会", "有", "不", "这", "那", "吗", "呢", "吧", "啊",
    "哦", "嗯", "呀", "哈", "么", "个", "们", "说", "到", "去", "看", "好",
    "没", "又", "还", "把", "被", "让", "给", "对", "与", "及", "或", "但",
    "如果", "因为", "所以", "但是", "然后", "现在", "什么", "怎么", "为什么",
    "今天", "明天", "昨天", "大家", "一下", "一个", "真的", "觉得", "知道",
    "哈哈", "哈哈哈", "hhh", "啊这", "草", "笑死", "不是", "没有", "可以",
    "这个", "那个", "这样", "那样", "意思", "时候", "东西", "朋友",
}

_NICKNAME_RE = re.compile(
    r"(?:我叫|我是|叫我|叫我一声|可以叫我|昵称是|外号是|大家都叫我)s*([\u4e00-\u9fff\w]{1,12})"
)


class GroupStats:
    """内存统计累积器 + 氛围分（每个群一个实例）"""

    def __init__(self, group_id):
        self.group_id = str(group_id)
        # 内存累积（flush 时写库）
        self.msg_buffer: list = []
        self.member_counts: dict = defaultdict(int)
        self.topic_counts: dict = defaultdict(int)
        self.activity_counts: dict = defaultdict(int)
        self.interaction_counts: dict = defaultdict(int)
        self.nickname_candidates: dict = defaultdict(
            lambda: defaultdict(int)
        )
        # 氛围分（内存态，定期持久化）
        self.atmosphere: float = 1.0
        self.last_bot_reply_ts: float = 0.0
        self._pending_reply: bool = False
        self._dirty: bool = False

    # ── 采集 ──

    def ingest(
        self, user_id: str, text: str,
        mentions: list, ts: float, is_bot: bool = False,
    ) -> None:
        """接收一条群消息的内存统计（不写盘）"""
        self.msg_buffer.append((self.group_id, str(user_id), text, ts))
        if not is_bot:
            self.member_counts[str(user_id)] += 1
            self._bump_topics(text)
            self.activity_counts[int(time.localtime(ts).tm_hour)] += 1
            for m in mentions:
                self.interaction_counts[f"{user_id}:{m}"] += 1
            nick = self._extract_nickname(text)
            if nick:
                self.nickname_candidates[str(user_id)][nick] += 1
            # 氛围分：bot 回复后的窗口期内有人接话 → 正反馈
            if self._pending_reply:
                self.atmosphere = min(
                    GROUP_ATMOSPHERE_MAX,
                    self.atmosphere + GROUP_ATMOSPHERE_BOOST,
                )
                self._pending_reply = False
                self._dirty = True
        self._dirty = True

    def _bump_topics(self, text: str) -> None:
        # 统一走 text_utils（归一化 + 领域/动态词典 + 分词缓存）
        from ..nonebot_plugin_memory.text_utils import normalize_text, tokenize
        try:
            for w in tokenize(normalize_text(text)):
                if w not in _STOPWORDS:
                    self.topic_counts[w] += 1
        except Exception:
            pass

    def _extract_nickname(self, text: str) -> str:
        m = _NICKNAME_RE.search(text)
        if m:
            return m.group(1).strip()
        return ""

    def note_bot_reply(self) -> None:
        """记录 bot 刚回复（开启接话窗口）"""
        self.last_bot_reply_ts = time.time()
        self._pending_reply = True

    def decay_atmosphere(self) -> None:
        """惰性衰减：窗口期已过仍无人接话 → 负反馈"""
        if (
            self._pending_reply
            and time.time() - self.last_bot_reply_ts > GROUP_ATMOSPHERE_WINDOW
        ):
            self.atmosphere = max(
                GROUP_ATMOSPHERE_MIN,
                self.atmosphere - GROUP_ATMOSPHERE_DECAY,
            )
            self._pending_reply = False
            self._dirty = True

    def get_adaptive_factor(self) -> float:
        self.decay_atmosphere()
        return self.atmosphere

    # ── flush 到群库 ──

    def flush(self, storage, db_path: str) -> int:  # noqa: C901, PLR0912
        """把内存累积写入库，返回写入的消息条数。storage 为 groupmind.storage 模块"""
        written = 0
        if self.msg_buffer:
            storage.insert_messages(db_path, self.msg_buffer)
            written = len(self.msg_buffer)
            self.msg_buffer.clear()
        if self.member_counts:
            now = time.time()
            for uid, cnt in self.member_counts.items():
                for _ in range(cnt):
                    storage.bump_member(db_path, uid, "", now)
            self.member_counts.clear()
        if self.topic_counts:
            now = time.time()
            for topic, cnt in self.topic_counts.items():
                for _ in range(min(cnt, 50)):
                    storage.bump_topic(db_path, topic, now)
            self.topic_counts.clear()
        if self.activity_counts:
            for hour, cnt in self.activity_counts.items():
                for _ in range(min(cnt, 50)):
                    storage.bump_activity(db_path, hour)
            self.activity_counts.clear()
        if self.interaction_counts:
            for k, cnt in self.interaction_counts.items():
                fid, tid = k.split(":", 1)
                for _ in range(min(cnt, 20)):
                    storage.bump_interaction(db_path, fid, tid)
            self.interaction_counts.clear()
        if self.nickname_candidates:
            for uid, cands in self.nickname_candidates.items():
                for nick, cnt in cands.items():
                    for _ in range(cnt):
                        storage.update_nickname_counts(db_path, uid, nick)
            self.nickname_candidates.clear()
        if self._dirty:
            storage.set_meta(
                db_path, "atmosphere", f"{self.atmosphere:.3f}"
            )
            self._dirty = False
        return written


# 全局统计实例缓存
_stats: dict = {}


def get_stats(group_id) -> GroupStats:
    gid = str(group_id)
    if gid not in _stats:
        _stats[gid] = GroupStats(gid)
    return _stats[gid]


def drop_stats(group_id) -> None:
    _stats.pop(str(group_id), None)


def all_group_keys() -> list:
    """所有有内存统计的群 id"""
    return list(_stats.keys())
