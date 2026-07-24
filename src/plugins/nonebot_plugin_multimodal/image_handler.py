"""
图片消息处理

接收 QQ 图片消息，下载并可选地通过 LLM vision API 进行理解。
"""

import os
import base64
import aiohttp
from typing import Optional

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment

from .config import IMAGE_CACHE_DIR, ENABLE_VISION


async def download_image(bot: Bot, url: str, file_name: str = "") -> Optional[str]:
    """下载 QQ 图片到本地"""
    os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    ext = ".jpg"
                    if not file_name:
                        file_name = f"{hash(url)}{ext}"
                    local_path = os.path.join(IMAGE_CACHE_DIR, file_name)
                    with open(local_path, "wb") as f:
                        f.write(await resp.read())
                    return local_path
    except Exception as e:
        logger.error(f"下载图片失败: {e}")
    return None


def image_to_base64(image_path: str) -> Optional[str]:
    """将本地图片转为 base64 字符串"""
    try:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        logger.error(f"图片转 base64 失败: {e}")
    return None


def extract_image_segments(event: MessageEvent) -> list:
    """从消息事件中提取所有图片段"""
    images = []
    for seg in event.message:
        if seg.type == "image":
            url = seg.data.get("url", "")
            file_id = seg.data.get("file", "") or seg.data.get("file_id", "")
            if url:
                images.append({"url": url, "file_id": file_id})
    return images


async def analyze_image_via_llm(llm_client, image_path: str) -> str:
    """
    通过 LLM Vision API 分析图片内容。

    注意：这需要 LLM API 支持 vision 能力（如 DeepSeek 的 vision 模型，
    或 OpenAI 的 GPT-4V）。当前 DeepSeek Chat 模型不完全支持图片。
    此功能作为预留接口。
    """
    if not ENABLE_VISION:
        return ""

    base64_img = image_to_base64(image_path)
    if not base64_img:
        return ""

    try:
        # OpenAI-compatible vision API 格式
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "请用一两句话简洁描述这张图片的内容。"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_img}"
                    }
                }
            ]
        }]
        response = await llm_client.chat_completion(
            messages=messages,
            temperature=0.3,
            max_tokens=200
        )
        return response.strip()
    except Exception as e:
        logger.error(f"图片分析失败: {e}")
        return ""


async def handle_image_message(bot: Bot, event: MessageEvent,
                               llm_client=None) -> Optional[str]:
    """
    处理包含图片的消息。

    返回图片描述文本（如果分析成功），否则返回 None。
    调用者可以将描述文本注入到对话上下文中。
    """
    images = extract_image_segments(event)
    if not images:
        return None

    descriptions = []
    for img_info in images[:3]:  # 最多处理 3 张图片
        local_path = await download_image(bot, img_info["url"], img_info["file_id"])
        if not local_path:
            continue

        if ENABLE_VISION and llm_client:
            desc = await analyze_image_via_llm(llm_client, local_path)
            if desc:
                descriptions.append(f"[图片内容: {desc}]")
            else:
                descriptions.append("[用户发送了一张图片]")
        else:
            descriptions.append("[用户发送了一张图片]")

    return "\n".join(descriptions) if descriptions else None
