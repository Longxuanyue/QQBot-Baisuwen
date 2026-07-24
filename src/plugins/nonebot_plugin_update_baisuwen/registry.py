"""
服务注册中心：管理所有子模块（ASR/TTS/记忆/LLM等）的初始化与状态。

所有服务通过 Registry 统一注册、初始化和关闭。
这解决了全局单例生命周期管理问题。
"""

from typing import Any, Callable, Dict, List, Optional, Awaitable
from nonebot import logger


class ServiceRegistry:
    """插件服务注册中心（单例模式）"""

    _instance: Optional["ServiceRegistry"] = None

    def __init__(self):
        self._services: Dict[str, Any] = {}
        self._factories: Dict[str, Callable[[], Awaitable[Any]]] = {}
        self._dependencies: Dict[str, List[str]] = {}
        self._initialized: List[str] = []  # 按初始化顺序排列

    @classmethod
    def get_instance(cls) -> "ServiceRegistry":
        """获取单例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(
        self,
        name: str,
        factory: Callable[[], Awaitable[Any]],
        *,
        depends_on: Optional[List[str]] = None,
    ) -> None:
        """
        注册一个服务。

        :param name: 服务名称（如 "asr", "tts", "llm", "memory"）
        :param factory: 异步工厂函数，返回初始化后的服务实例
        :param depends_on: 此服务依赖的其他服务名称列表
        """
        self._factories[name] = factory
        self._dependencies[name] = depends_on or []
        logger.debug(f"服务已注册: {name} (依赖: {self._dependencies[name]})")

    def get(self, name: str) -> Optional[Any]:
        """获取已初始化的服务实例"""
        return self._services.get(name)

    def has(self, name: str) -> bool:
        """检查服务是否已注册且已初始化"""
        return name in self._services and self._services[name] is not None

    def is_registered(self, name: str) -> bool:
        """检查服务是否已注册"""
        return name in self._factories

    async def init_all(self) -> None:
        """
        按依赖拓扑顺序初始化所有服务。
        若初始化失败，记录错误但不阻止其他服务初始化。
        """
        # 拓扑排序
        init_order = self._topological_sort()

        for name in init_order:
            factory = self._factories[name]
            try:
                logger.info(f"正在初始化服务: {name} ...")
                instance = await factory()
                self._services[name] = instance
                self._initialized.append(name)
                logger.info(f"服务初始化完成: {name}")
            except Exception as e:
                logger.error(f"服务初始化失败 [{name}]: {e}")
                self._services[name] = None  # 标记为不可用

    async def shutdown_all(self) -> None:
        """按初始化的逆序关闭所有服务"""
        for name in reversed(self._initialized):
            service = self._services.get(name)
            if service is None:
                continue
            try:
                if hasattr(service, "close"):
                    close_method = service.close
                    if callable(close_method):
                        import asyncio
                        if asyncio.iscoroutinefunction(close_method):
                            await close_method()
                        else:
                            close_method()
                logger.info(f"服务已关闭: {name}")
            except Exception as e:
                logger.error(f"服务关闭失败 [{name}]: {e}")

    def status(self) -> Dict[str, bool]:
        """返回所有已注册服务的可用状态"""
        return {
            name: self._services.get(name) is not None
            for name in self._factories
        }

    def get_status_text(self) -> str:
        """生成人类可读的服务状态报告"""
        lines = ["--- 服务状态 ---"]
        for name in self._factories:
            available = "✓" if self._services.get(name) is not None else "✗"
            lines.append(f"  [{available}] {name}")
        return "\n".join(lines)

    def _topological_sort(self) -> List[str]:
        """
        对注册的服务进行拓扑排序（Kahn 算法），
        确保依赖的服务在被依赖者之前初始化。
        """
        # 构建入度表
        in_degree: Dict[str, int] = {name: 0 for name in self._factories}
        for name, deps in self._dependencies.items():
            for dep in deps:
                if dep in in_degree:
                    in_degree[name] += 1

        # 没有依赖的服务先初始化
        queue = [name for name, deg in in_degree.items() if deg == 0]
        result = []

        while queue:
            name = queue.pop(0)
            result.append(name)
            # 减少依赖此服务的其他服务的入度
            for other, deps in self._dependencies.items():
                if name in deps:
                    in_degree[other] -= 1
                    if in_degree[other] == 0:
                        queue.append(other)

        # 检查是否有循环依赖
        if len(result) != len(self._factories):
            missing = set(self._factories) - set(result)
            logger.warning(f"检测到循环依赖，以下服务将跳过拓扑排序直接初始化: {missing}")
            result.extend(missing)

        return result


# 全局注册中心单例
registry = ServiceRegistry.get_instance()
