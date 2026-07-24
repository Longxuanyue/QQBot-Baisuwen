"""
多轮对话管理插件 (nonebot_plugin_dialog)

管理每个用户/群聊的有状态对话上下文，支持：
- 会话超时自动清理
- 滑动窗口上下文
- 对话历史持久化
- 话题切换检测
"""

import time
import asyncio
from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple
from nonebot import logger

from .config import DIALOG_MAX_TURNS, DIALOG_SESSION_TTL


class DialogSession:
    """单个对话会话"""

    __slots__ = (
        "session_id", "messages", "current_topic",
        "created_at", "last_active", "user_id", "is_group"
    )

    def __init__(self, session_id: str, user_id: str = "", is_group: bool = False):
        self.session_id = session_id
        self.messages: deque = deque(maxlen=DIALOG_MAX_TURNS * 2)  # user+assistant pairs
        self.current_topic: str = ""
        self.created_at: float = time.time()
        self.last_active: float = time.time()
        self.user_id = user_id
        self.is_group = is_group

    def add_turn(self, role: str, content: str):
        """添加一轮对话"""
        self.messages.append({"role": role, "content": content})
        self.last_active = time.time()

    def get_context(self, last_n: int = 10) -> List[Dict[str, str]]:
        """获取最近 N 轮对话上下文"""
        return list(self.messages)[-last_n * 2:] if self.messages else []

    def is_expired(self, ttl_seconds: float = DIALOG_SESSION_TTL) -> bool:
        """检查会话是否过期"""
        return (time.time() - self.last_active) > ttl_seconds

    def clear(self):
        """清空对话历史"""
        self.messages.clear()
        self.current_topic = ""

    def __repr__(self) -> str:
        return (
            f"DialogSession(id={self.session_id}, "
            f"turns={len(self.messages)//2}, topic={self.current_topic})"
        )


class DialogManager:
    """多轮对话管理器（单例）"""

    _instance: Optional["DialogManager"] = None

    def __init__(self):
        self._sessions: Dict[str, DialogSession] = {}
        self._cleanup_task: Optional[asyncio.Task] = None

    @classmethod
    def get_instance(cls) -> "DialogManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── 会话管理 ──

    def _session_id(self, user_id: str, group_id: Optional[int] = None) -> str:
        """生成会话 ID"""
        if group_id:
            return f"group_{group_id}"
        return f"private_{user_id}"

    def get_or_create_session(
        self, user_id: str, group_id: Optional[int] = None
    ) -> DialogSession:
        """获取或创建会话"""
        sid = self._session_id(user_id, group_id)
        if sid not in self._sessions:
            self._sessions[sid] = DialogSession(
                sid, user_id=user_id, is_group=(group_id is not None)
            )
            logger.debug(f"创建新会话: {sid}")
        return self._sessions[sid]

    def add_turn(self, user_id: str, role: str, content: str,
                 group_id: Optional[int] = None):
        """添加一轮对话到用户会话"""
        session = self.get_or_create_session(user_id, group_id)
        session.add_turn(role, content)

    def get_context(self, user_id: str, group_id: Optional[int] = None,
                    last_n: int = 10) -> List[Dict[str, str]]:
        """获取用户会话的最近 N 轮对话"""
        sid = self._session_id(user_id, group_id)
        session = self._sessions.get(sid)
        if session is None:
            return []
        return session.get_context(last_n)

    def get_context_text(self, user_id: str, group_id: Optional[int] = None,
                         last_n: int = 5) -> str:
        """将最近对话格式化为文本（用于注入 LLM prompt）"""
        context = self.get_context(user_id, group_id, last_n)
        if not context:
            return ""
        lines = []
        for msg in context:
            role_label = "用户" if msg["role"] == "user" else "你"
            lines.append(f"{role_label}: {msg['content']}")
        return "\n".join(lines)

    def clear(self, user_id: str, group_id: Optional[int] = None):
        """清除会话历史"""
        sid = self._session_id(user_id, group_id)
        if sid in self._sessions:
            self._sessions[sid].clear()
            logger.info(f"已清除会话: {sid}")

    # ── 话题管理 ──

    def set_topic(self, user_id: str, topic: str,
                  group_id: Optional[int] = None):
        """设置当前话题"""
        session = self.get_or_create_session(user_id, group_id)
        old_topic = session.current_topic
        session.current_topic = topic
        if old_topic and old_topic != topic:
            logger.debug(f"话题切换: {old_topic} → {topic}")

    def get_topic(self, user_id: str,
                  group_id: Optional[int] = None) -> str:
        """获取当前话题"""
        sid = self._session_id(user_id, group_id)
        session = self._sessions.get(sid)
        return session.current_topic if session else ""

    def detect_topic_change(self, user_id: str, new_message: str,
                            group_id: Optional[int] = None) -> bool:
        """简单话题变更检测：基于关键词变化"""
        import jieba
        session = self.get_or_create_session(user_id, group_id)
        if not session.messages:
            return False

        # 从最近 2 轮取词
        recent_text = " ".join(
            m["content"] for m in list(session.messages)[-4:]
        )
        old_words = set(jieba.lcut(recent_text))
        new_words = set(jieba.lcut(new_message))

        # 如果新词占比超过 70%，视为话题变化
        if not new_words:
            return False
        overlap = len(new_words & old_words) / len(new_words)
        return overlap < 0.3

    # ── 维护 ──

    async def cleanup_stale(self, ttl_seconds: float = DIALOG_SESSION_TTL) -> int:
        """清理过期会话，返回清理数量"""
        expired = [
            sid for sid, s in self._sessions.items()
            if s.is_expired(ttl_seconds)
        ]
        for sid in expired:
            logger.debug(f"清理过期会话: {sid}")
            del self._sessions[sid]
        if expired:
            logger.info(f"清理了 {len(expired)} 个过期会话")
        return len(expired)

    def start_auto_cleanup(self, interval_seconds: int = 600):
        """启动自动清理任务（每 10 分钟运行一次）"""
        async def _loop():
            while True:
                await asyncio.sleep(interval_seconds)
                await self.cleanup_stale()

        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(_loop())
            logger.info("会话自动清理任务已启动")

    def stop_auto_cleanup(self):
        """停止自动清理任务"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            logger.info("会话自动清理任务已停止")

    # ── 统计 ──

    def stats(self) -> Dict:
        """返回会话统计信息"""
        total = len(self._sessions)
        active = sum(1 for s in self._sessions.values() if not s.is_expired())
        total_turns = sum(len(s.messages) // 2 for s in self._sessions.values())
        return {
            "total_sessions": total,
            "active_sessions": active,
            "expired_sessions": total - active,
            "total_turns": total_turns,
        }


# 全局单例
dialog_manager = DialogManager.get_instance()
