import os
import httpx
from typing import List, Dict, Optional
from nonebot import logger
from .config import plugin_config


class MissingAPIKeyError(Exception):
    """API key 未配置时抛出的异常"""
    pass


class DeepseekClient:
    """DeepSeek API 客户端（惰性初始化 httpx client）"""

    def __init__(self):
        # 从统一配置读取（config.py 已确保 .env 正确加载）
        self.api_key = plugin_config.deepseek_api_key
        self.api_base = plugin_config.deepseek_api_base.rstrip('/')
        self.model = plugin_config.deepseek_model
        self.timeout = plugin_config.http_timeout
        self._client: Optional[httpx.AsyncClient] = None

        if not self.api_key:
            logger.warning(
                "⚠️ DEEPSEEK_API_KEY 未设置！"
                "请在项目根目录的 .env 文件中添加: DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx "
                "（可从 https://platform.deepseek.com/api_keys 获取）"
            )

    @property
    def client(self) -> httpx.AsyncClient:
        """惰性初始化 httpx AsyncClient"""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
            logger.debug("httpx AsyncClient 已创建 (惰性初始化)")
        return self._client

    async def chat_completion(
        self, messages: List[Dict[str, str]],
        temperature: float = 0.7, max_tokens: int = 2000, **kwargs
    ) -> str:
        if not self.api_key:
            raise MissingAPIKeyError(
                "DEEPSEEK_API_KEY 未设置，无法调用 LLM。"
                "请在项目根目录的 .env 文件中添加: DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx"
            )

        url = f"{self.api_base}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs
        }
        response = await self.client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    async def close(self):
        """关闭 HTTP 客户端"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.debug("httpx AsyncClient 已关闭")


# 全局实例（惰性初始化，首次 API 调用时才创建 httpx client）
llm_client = DeepseekClient()