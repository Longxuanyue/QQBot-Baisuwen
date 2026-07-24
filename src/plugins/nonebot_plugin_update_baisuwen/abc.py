"""
抽象基类（ABC）：定义所有可扩展服务模块的接口约定。

新功能模块只需实现对应的 ABC 并注册到 ServiceRegistry 即可集成。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


# ──────────────────────────────────────────────
# 基础服务接口
# ──────────────────────────────────────────────

class BaseService(ABC):
    """所有可注册服务的基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """服务唯一名称"""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """服务是否可用（已初始化且功能正常）"""
        ...

    def close(self) -> None:
        """释放资源（可选重写）"""
        pass


# ──────────────────────────────────────────────
# LLM 接口
# ──────────────────────────────────────────────

class BaseLLMClient(BaseService, ABC):
    """LLM 客户端抽象接口"""

    @abstractmethod
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ) -> str:
        """发送消息并返回 LLM 回复文本"""
        ...

    @abstractmethod
    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        ...


# ──────────────────────────────────────────────
# 语音识别接口
# ──────────────────────────────────────────────

class BaseASREngine(BaseService, ABC):
    """语音识别引擎抽象接口"""

    @abstractmethod
    def transcribe_file(self, audio_path: str, language: Optional[str] = None, **kwargs) -> str:
        """识别音频文件，返回文本"""
        ...

    @abstractmethod
    def transcribe_audio_array(self, audio_np, sample_rate: int,
                                language: Optional[str] = None, **kwargs) -> str:
        """识别 numpy 音频数组，返回文本"""
        ...

    def close(self) -> None:
        """释放模型显存"""
        pass


# ──────────────────────────────────────────────
# 语音合成接口
# ──────────────────────────────────────────────

class BaseTTSEngine(BaseService, ABC):
    """语音合成引擎抽象接口"""

    @abstractmethod
    def synthesize(self, text: str, speed: Optional[float] = None,
                   noise_scale: Optional[float] = None,
                   noise_scale_w: Optional[float] = None):
        """
        合成语音，返回 (sample_rate, audio_numpy_array)
        """
        ...

    def close(self) -> None:
        """释放模型显存"""
        pass


# ──────────────────────────────────────────────
# 记忆存储接口
# ──────────────────────────────────────────────

class BaseMemoryBackend(ABC):
    """记忆存储后端抽象接口"""

    @abstractmethod
    def store_memory(self, content: str, importance: float = 0.6) -> bool:
        """存储一条记忆"""
        ...

    @abstractmethod
    def retrieve_memories(self, query: str, top_k: int = 5,
                          update_access: bool = True,
                          conversation_history: Optional[List[str]] = None) -> List[Dict]:
        """检索相关记忆"""
        ...

    @abstractmethod
    def cleanup(self) -> None:
        """清理低权重/超量记忆"""
        ...

    @abstractmethod
    def upgrade_and_deduplicate(self) -> None:
        """升级记忆到长期库 + 去重"""
        ...


# ──────────────────────────────────────────────
# 对话管理接口
# ──────────────────────────────────────────────

class BaseDialogManager(ABC):
    """对话管理器抽象接口"""

    @abstractmethod
    def add_turn(self, session_id: str, role: str, content: str) -> None:
        """添加一轮对话"""
        ...

    @abstractmethod
    def get_context(self, session_id: str, last_n: int = 10) -> List[Dict[str, str]]:
        """获取最近 N 轮对话上下文"""
        ...

    @abstractmethod
    def clear(self, session_id: str) -> None:
        """清除某个会话的上下文"""
        ...

    @abstractmethod
    async def cleanup_stale(self, ttl_seconds: float = 1800.0) -> int:
        """清理过期会话，返回清理数量"""
        ...


# ──────────────────────────────────────────────
# 情感分析接口
# ──────────────────────────────────────────────

class BaseSentimentAnalyzer(ABC):
    """情感分析器抽象接口"""

    @abstractmethod
    def analyze(self, text: str) -> Dict[str, Any]:
        """
        分析文本情感，返回:
        {
            "sentiment": str,        # positive/negative/neutral
            "emotion": str,          # happy/sad/angry/anxious/calm/excited
            "confidence": float,     # 0~1
        }
        """
        ...


# ──────────────────────────────────────────────
# 用户画像接口
# ──────────────────────────────────────────────

class BaseProfileBuilder(ABC):
    """用户画像构建器抽象接口"""

    @abstractmethod
    def build_profile(self, user_id: str) -> Dict[str, Any]:
        """构建用户画像，返回结构化数据"""
        ...

    @abstractmethod
    def get_profile_summary(self, user_id: str) -> str:
        """获取用户画像的文本摘要（用于注入 system prompt）"""
        ...
