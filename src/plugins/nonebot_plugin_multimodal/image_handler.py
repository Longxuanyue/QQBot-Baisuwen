"""
图片消息处理

接收 QQ 图片消息，下载并可选地通过 LLM vision API 进行理解。
"""

import io
import os
import re
import time
import asyncio
import base64
import ipaddress
import shutil
import socket
import urllib.parse
from typing import Optional

import aiohttp
from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment

from .config import IMAGE_CACHE_DIR, ENABLE_VISION

# ── 下载安全限制 ──

# 单张图片最大下载字节数（20MB，QQ 图片通常 < 10MB）
IMAGE_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024

# 下载超时（秒）
DOWNLOAD_TIMEOUT_SECONDS = 15

# 允许的图片扩展名白名单
IMAGE_EXT_WHITELIST = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

# 缓存文件名白名单（仅字母数字、下划线、点、短横线，不含路径分隔符）
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _is_safe_download_url(url: str) -> tuple[bool, str]:
    """
    校验 URL 是否允许 Bot 代下载。

    拒绝：非 http/https、无法解析的域名、私网/环回/链路本地/组播/保留地址。
    防止 SSRF 探测内网服务。
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, "仅支持 http/https 协议"
    host = parsed.hostname
    if not host:
        return False, "无效 URL"

    try:
        infos = socket.getaddrinfo(
            host, parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror:
        return False, f"域名无法解析: {host}"
    except OSError:
        return False, f"域名解析失败: {host}"

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_unspecified or ip.is_reserved):
            return False, f"拒绝访问内网/保留地址: {ip}"

    return True, ""


async def _safe_fetch_bytes(session: aiohttp.ClientSession, url: str,
                            max_bytes: int) -> Optional[tuple[bytes, str]]:
    """
    带安全校验的下载：每跳校验目标地址（防重定向逃逸）、
    大小限制（防磁盘耗尽）、超时（防连接挂起）。

    返回 (内容字节, Content-Type)，失败或超限返回 None。
    """
    current = url
    for _ in range(4):  # 最多 3 次重定向
        # socket.getaddrinfo 为阻塞调用，迁移到线程池避免卡住事件循环
        ok, reason = await asyncio.to_thread(_is_safe_download_url, current)
        if not ok:
            logger.warning(f"[下载安全] 拒绝下载 {current}: {reason}")
            return None

        try:
            async with session.get(
                current, allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=DOWNLOAD_TIMEOUT_SECONDS),
            ) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("Location", "")
                    if not loc:
                        return None
                    current = urllib.parse.urljoin(current, loc)
                    continue
                if resp.status != 200:
                    logger.warning(f"[下载安全] HTTP {resp.status}: {current}")
                    return None

                chunks = []
                total = 0
                async for chunk in resp.content.iter_chunked(65536):
                    total += len(chunk)
                    if total > max_bytes:
                        logger.warning(
                            f"[下载安全] 文件超过大小限制 "
                            f"({max_bytes // 1024 // 1024}MB): {current}"
                        )
                        return None
                    chunks.append(chunk)
                return b"".join(chunks), resp.headers.get("Content-Type", "")
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as e:
            logger.warning(f"[下载安全] 下载失败 {current}: {e}")
            return None

    logger.warning(f"[下载安全] 重定向次数过多: {url}")
    return None


def _safe_cache_filename(url: str, ext: str) -> str:
    """根据 URL 生成安全的缓存文件名（避免依赖消息中的可控字段）"""
    return f"{hash(url)}{ext}"


def _guess_image_ext(url: str, content_type: str = "") -> str:
    """从 URL 或 Content-Type 推断图片扩展名，非白名单回退 .jpg"""
    url_path = urllib.parse.urlparse(url).path
    _, ext = os.path.splitext(url_path)
    if ext.lower() in IMAGE_EXT_WHITELIST:
        return ext.lower()
    ct_map = {
        "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
        "image/webp": ".webp", "image/bmp": ".bmp",
    }
    for ct_key, ext_val in ct_map.items():
        if ct_key in content_type:
            return ext_val
    return ".jpg"


async def download_image(bot: Bot, url: str, file_name: str = "") -> Optional[str]:
    """下载 QQ 图片到本地"""
    os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)
    try:
        if not url.startswith(("http://", "https://")):
            logger.warning(f"[下载安全] 拒绝非 http(s) 图片地址: {url}")
            return None

        async with aiohttp.ClientSession() as session:
            result = await _safe_fetch_bytes(session, url, IMAGE_MAX_DOWNLOAD_BYTES)
            if result is None:
                return None
            data, content_type = result
            ext = _guess_image_ext(url, content_type)

            # ── 文件名消毒（H3） ──
            # 消息段 file/file_id 字段可控，仅取 basename 并校验白名单，
            # 非法则回退为基于 URL 哈希的安全文件名，杜绝路径穿越。
            fname = file_name
            if fname:
                fname = os.path.basename(fname.replace("\\", "/"))
                if not fname or ".." in fname or not _SAFE_FILENAME_RE.match(fname):
                    fname = ""
            if not fname:
                fname = _safe_cache_filename(url, ext)

            local_path = os.path.join(IMAGE_CACHE_DIR, fname)
            with open(local_path, "wb") as f:
                f.write(data)
            return local_path
    except Exception as e:
        logger.error(f"下载图片失败: {e}")
    return None


async def cleanup_image_cache(max_age_days: int = 7) -> int:
    """清理 image_cache 中超过 max_age_days 未修改的缓存文件，返回删除数量。"""
    cutoff = time.time() - max_age_days * 86400
    deleted = 0
    if not os.path.isdir(IMAGE_CACHE_DIR):
        return 0
    for fname in os.listdir(IMAGE_CACHE_DIR):
        fpath = os.path.join(IMAGE_CACHE_DIR, fname)
        try:
            if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                os.remove(fpath)
                deleted += 1
        except OSError:
            continue
    if deleted:
        logger.info(f"image_cache 自动清理: 删除 {deleted} 个超过 {max_age_days} 天的缓存文件")
    return deleted


def image_to_base64(image_path: str) -> Optional[str]:
    """将本地图片转为 base64 字符串"""
    try:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        logger.error(f"图片转 base64 失败: {e}")
    return None


async def _resolve_image_source(bot: Bot, seg) -> dict:
    """从 image/file 消息段解析出可下载的图片来源。

    返回 {"url": ...} 或 {"path": ...}（本地缓存路径），均无法解析时返回空 dict。
    """
    data = seg.data
    url = data.get("url", "") or ""
    if url:
        return {"url": url}
    file_key = data.get("file_id", "") or data.get("file", "") or ""
    if not file_key:
        logger.warning(f"[多模态] 图片段既无 url 也无 file/file_id，跳过: {data}")
        return {}

    # image 段优先 get_image，file 段用 get_file（NapCat/LLOneBot/Lagrange 均支持）
    apis = ("get_image", "get_file") if seg.type == "image" else ("get_file", "get_image")
    for api in apis:
        try:
            info = await bot.call_api(api, file=file_key)
        except Exception as e:
            logger.warning(f"[多模态] {api} 解析失败 (file={file_key}): {e!r}")
            continue
        if not isinstance(info, dict):
            logger.warning(f"[多模态] {api} 返回异常: {info}")
            continue
        u = info.get("url", "") or ""
        if u:
            logger.info(f"[多模态] {api} 解析出图片 url (type={seg.type})")
            return {"url": u}
        p = info.get("path", "") or ""
        if p:
            logger.info(f"[多模态] {api} 返回本地缓存路径 (type={seg.type})")
            return {"path": p}
    return {}


async def extract_image_segments(bot: Bot, event: MessageEvent) -> list:
    """从消息事件中提取所有可下载的图片段（image 段 + 图片类 file 段）。

    优先使用消息自带的 url；缺失时通过 OneBot get_image/get_file API
    解析出 url 或本地缓存路径（协议端与 bot 同机部署时可直读），
    避免不同协议实现下图片段无 url 导致静默跳过。
    """
    resolved: list[dict] = []
    for seg in event.message:
        if seg.type == "image":
            pass
        elif seg.type == "file":
            # 文件段仅当文件名看起来是图片时才处理
            fname = str(seg.data.get("file", "") or "").lower()
            ext = os.path.splitext(fname)[1]
            if ext not in IMAGE_EXT_WHITELIST:
                logger.warning(
                    f"[多模态] 文件段非图片（{seg.data.get('file')}），跳过"
                )
                continue
        else:
            continue
        src = await _resolve_image_source(bot, seg)
        if not src:
            logger.warning(
                f"[多模态] 图片段无法解析出下载来源，跳过 | 段类型={seg.type} | 数据={seg.data}"
            )
            continue
        resolved.append({
            **src,
            "file_id": seg.data.get("file_id", "") or seg.data.get("file", "") or "",
        })
    if not resolved:
        logger.warning(
            f"[多模态] 未提取到可下载的图片段 | 消息段类型: {[s.type for s in event.message]}"
        )
    return resolved


async def analyze_image_via_llm(
    llm_client, image_path: str, model: Optional[str] = None,
    max_tokens: int = 4096,
) -> str:
    """
    通过 LLM Vision API 分析图片内容。
    :param model: 视觉模型名（如 deepseek-v4-flash-vision-exp），
                  传入后覆盖 llm_client 的默认模型。
    :param max_tokens: 输出 token 上限。该模型带推理，复杂图片会先消耗
                  较多推理 token，预算过小会导致 content 为空，需留足余量。

    注意：这需要 LLM API 支持 vision 能力。DeepSeek 多模态模型
    （deepseek-v4-flash-vision-exp）可通过 LLM_VISION_MODEL 配置使用。
    """
    if not ENABLE_VISION:
        return ""

    # 统一转码为 JPEG：GIF/WEBP/BMP 等格式也能被视觉 API 接受；
    # 转码失败（如文件损坏）则退回原始字节
    base64_img = ""
    try:
        from PIL import Image as PILImage
        with PILImage.open(image_path) as im:
            im.load()
            logger.info(
                f"[多模态] 图片解码成功 | 格式={im.format} 尺寸={im.size}"
            )
            buf = io.BytesIO()
            im.convert("RGB").save(buf, format="JPEG", quality=92)
            base64_img = base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        logger.warning(f"[多模态] 图片转码失败，使用原始字节: {e!r}")
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
        kwargs = {}
        if model:
            kwargs["model"] = model
        response = await llm_client.chat_completion(
            messages=messages,
            temperature=0.3,
            max_tokens=max_tokens,
            **kwargs,
        )
        logger.info(f"[多模态] 视觉模型返回: {response[:150]!r}")
        return response.strip()
    except Exception as e:
        logger.error(f"图片分析失败: {e}")
        return ""


async def handle_image_message(bot: Bot, event: MessageEvent,
                               llm_client=None,
                               model: Optional[str] = None,
                               max_tokens: int = 4096) -> Optional[str]:
    """
    处理包含图片的消息。

    返回图片描述文本（如果分析成功），否则返回 None。
    调用者可以将描述文本注入到对话上下文中。

    v2 优化：多张图片并发下载/分析，缩短消息处理耗时。
    """
    images = await extract_image_segments(bot, event)
    if not images:
        logger.warning(
            f"[多模态] 未提取到可下载的图片段 | 消息段类型: "
            f"{[s.type for s in event.message]}"
        )
        return None

    async def _process_one(img_info: dict) -> str:
        # 本地缓存路径（get_file 返回的协议端本地文件，与 bot 同机部署）直读
        if img_info.get("path"):
            src = img_info["path"]
            if not os.path.isfile(src):
                logger.warning(f"[多模态] 本地缓存图片不存在: {src}")
                return ""
            os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)
            fname = os.path.basename(src) or _safe_cache_filename(src, ".img")
            local_path = os.path.join(IMAGE_CACHE_DIR, fname)
            try:
                shutil.copyfile(src, local_path)
            except OSError as e:
                logger.warning(f"[多模态] 本地图片复制失败: {e!r}")
                return ""
        else:
            local_path = await download_image(bot, img_info["url"], img_info["file_id"])
            if not local_path:
                return ""

        if ENABLE_VISION and llm_client:
            desc = await analyze_image_via_llm(
                llm_client, local_path, model=model, max_tokens=max_tokens
            )
            if desc:
                return f"[图片内容: {desc}]"
        return "[用户发送了一张图片]"

    # 最多处理 3 张图片，并发执行
    results = await asyncio.gather(
        *(_process_one(img) for img in images[:3])
    )
    descriptions = [r for r in results if r]
    return "\n".join(descriptions) if descriptions else None
