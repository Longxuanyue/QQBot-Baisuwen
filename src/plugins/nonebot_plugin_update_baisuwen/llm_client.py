"""
DeepSeek API 客户端（OpenAI 兼容协议）

v2 优化：
- 失败重试 + 指数退避（429 / 5xx / 网络错误）
- 流式输出支持（chat_completion_stream）
"""

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any, Optional

import httpx
from nonebot import logger

from .config import plugin_config

# 5xx 状态码阈值（>= 该值视为服务端错误，值得重试）
_SERVER_ERROR_THRESHOLD = 500


class MissingAPIKeyError(Exception):
    """API key 未配置时抛出的异常"""

    def __init__(self, message: str = "DEEPSEEK_API_KEY 未设置") -> None:
        super().__init__(message)


class DeepseekClient:
    """DeepSeek API 客户端（惰性初始化 httpx client）"""

    def __init__(self) -> None:
        # 从统一配置读取（config.py 已确保 .env 正确加载）
        self.api_key = plugin_config.deepseek_api_key
        self.api_base = plugin_config.deepseek_api_base.rstrip("/")
        self.model = plugin_config.deepseek_model
        self.timeout = plugin_config.http_timeout
        self.max_retries = plugin_config.llm_max_retries
        self.retry_backoff = plugin_config.llm_retry_backoff
        self._client: Optional[httpx.AsyncClient] = None

        if not self.api_key:
            logger.warning(
                "⚠️ DEEPSEEK_API_KEY 未设置！"
                "请在项目根目录的 .env 文件中添加: "
                "DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx"
                "（可从 https://platform.deepseek.com/api_keys 获取）"
            )

    @property
    def client(self) -> httpx.AsyncClient:
        """惰性初始化 httpx AsyncClient"""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
            logger.debug("httpx AsyncClient 已创建 (惰性初始化)")
        return self._client

    def _build_payload(
        self, messages: list[dict],
        temperature: float, max_tokens: int, **kwargs: Any
    ) -> dict:
        return {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }

    def _should_retry(self, exc: Exception) -> bool:
        """判断异常是否值得重试（429 / 5xx / 网络层错误）"""
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            return status in (408, 429) or status >= _SERVER_ERROR_THRESHOLD
        return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))

    async def _wait_backoff(self, attempt: int) -> None:
        """指数退避等待：backoff * 2^(attempt-1)，上限 10s"""
        delay = min(self.retry_backoff * (2 ** max(0, attempt - 1)), 10.0)
        logger.warning(
            f"LLM 调用失败，{delay:.1f}s 后重试 "
            f"(第 {attempt}/{self.max_retries} 次)"
        )
        await asyncio.sleep(delay)

    async def chat_completion(
        self, messages: list[dict],
        temperature: float = 0.7, max_tokens: int = 2000, **kwargs: Any
    ) -> str:
        if not self.api_key:
            logger.warning(
                "DEEPSEEK_API_KEY 未设置，请在 .env 中配置后重启 Bot"
            )
            raise MissingAPIKeyError

        url = f"{self.api_base}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(
            messages, temperature, max_tokens, stream=False, **kwargs
        )

        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 2):
            try:
                response = await self.client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"]
            except Exception as e:  # noqa: PERF203, BLE001 - 重试需捕获任意网络/状态异常
                last_exc = e
                if not self._should_retry(e) or attempt > self.max_retries:
                    break
                await self._wait_backoff(attempt)
        raise last_exc  # type: ignore[misc]

    @staticmethod
    async def _iter_deltas(response: Any) -> AsyncGenerator[str, None]:
        """解析 SSE 流，逐段产出内容增量"""
        async for line in response.aiter_lines():
            if not line or not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                return
            try:
                chunk = json.loads(data)
                delta = chunk["choices"][0].get("delta", {}).get("content")
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
            if delta:
                yield delta

    async def chat_completion_stream(
        self, messages: list[dict],
        temperature: float = 0.7, max_tokens: int = 2000, **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        """流式输出：逐段 yield 增量文本。失败重试会重新开始整个流。"""
        if not self.api_key:
            logger.warning(
                "DEEPSEEK_API_KEY 未设置，请在 .env 中配置后重启 Bot"
            )
            raise MissingAPIKeyError

        url = f"{self.api_base}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(
            messages, temperature, max_tokens, stream=True, **kwargs
        )

        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 2):
            completed = False
            try:
                async with self.client.stream(
                    "POST", url, json=payload, headers=headers
                ) as response:
                    response.raise_for_status()
                    async for delta in self._iter_deltas(response):
                        yield delta
                    completed = True
            except Exception as e:  # noqa: BLE001 - 重试需捕获任意网络/状态异常
                last_exc = e
                if not self._should_retry(e) or attempt > self.max_retries:
                    break
                await self._wait_backoff(attempt)
            if completed:
                return
        raise last_exc  # type: ignore[misc]

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.debug("httpx AsyncClient 已关闭")


# 全局实例（惰性初始化，首次 API 调用时才创建 httpx client）
llm_client = DeepseekClient()
