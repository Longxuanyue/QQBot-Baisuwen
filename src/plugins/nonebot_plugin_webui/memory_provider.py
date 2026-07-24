"""
MemoryProvider 抽象接口 — 解耦 WebUI 与记忆存储实现
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MemoryEntry:
    """单条记忆"""
    id: str
    content: str
    importance: float = 0.5
    strength: float = 0.5
    access_count: int = 0
    last_accessed: str = ""
    source: str = "short"        # "short" | "long"
    created_at: str = ""


@dataclass
class MemoryQueryResult:
    """记忆查询结果（含分页信息）"""
    entries: list[MemoryEntry] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    user_id: str = ""


@dataclass
class MemoryStats:
    """用户记忆统计"""
    user_id: str = ""
    short_count: int = 0
    long_count: int = 0
    total_count: int = 0
    avg_importance: float = 0.0
    avg_strength: float = 0.0
    max_access_count: int = 0


class MemoryProvider(ABC):
    """
    记忆存储后端抽象接口。

    由记忆插件（如 nonebot_plugin_memory）实现并注册到 registry，
    WebUI 通过 registry 调用，不关心底层存储细节（SQLite / JSON / Redis）。
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """后端名称（如 "SQLite"）"""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """后端是否可用（数据库存在、连接正常等）"""
        ...

    @abstractmethod
    async def get_all_users(self) -> list[str]:
        """获取所有有记忆数据的用户 ID 列表"""
        ...

    @abstractmethod
    async def get_memories(
        self,
        user_id: str,
        page: int = 1,
        page_size: int = 50,
        search: Optional[str] = None,
    ) -> MemoryQueryResult:
        """分页获取用户记忆，支持搜索"""
        ...

    @abstractmethod
    async def delete_memory(self, user_id: str, memory_id: str) -> bool:
        """删除单条记忆"""
        ...

    @abstractmethod
    async def delete_all_memories(self, user_id: str) -> int:
        """清空用户全部记忆，返回删除条数"""
        ...

    @abstractmethod
    async def get_stats(self, user_id: str) -> MemoryStats:
        """获取用户记忆统计"""
        ...

    @abstractmethod
    async def export_all(self) -> dict:
        """
        导出全部记忆数据（供备份使用）。
        返回可 JSON 序列化的字典。
        """
        ...


# ── 注册表 ──

class MemoryProviderRegistry:
    """MemoryProvider 注册表"""

    def __init__(self):
        self._provider: Optional[MemoryProvider] = None

    def register(self, provider: MemoryProvider):
        """注册记忆后端"""
        self._provider = provider

    def get(self) -> Optional[MemoryProvider]:
        """获取当前注册的记忆后端"""
        return self._provider

    @property
    def has_provider(self) -> bool:
        return self._provider is not None and self._provider.is_available()


memory_registry = MemoryProviderRegistry()
