import os
import asyncio
import ipaddress
import socket
import urllib.parse
import aiohttp
from typing import Optional
from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, MessageSegment

# 语音文件缓存目录
VOICE_CACHE_DIR = "voice_cache"

# ── 下载安全限制 ──

# 单文件最大下载字节数（语音 30MB / 图片 20MB）
VOICE_MAX_DOWNLOAD_BYTES = 30 * 1024 * 1024
IMAGE_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024

# 下载超时（秒）
DOWNLOAD_TIMEOUT_SECONDS = 15

# 允许的扩展名白名单（语音 / 图片）
AUDIO_EXT_WHITELIST = {".silk", ".amr", ".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".spx"}
IMAGE_EXT_WHITELIST = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


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
        ok, reason = _is_safe_download_url(current)
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


async def _safe_download_and_save(session: aiohttp.ClientSession, url: str,
                                  cache_dir: str, max_bytes: int,
                                  ext_whitelist: set[str],
                                  ext_hint: str = "") -> Optional[str]:
    """
    安全下载文件并保存到缓存目录（文件名基于 URL 哈希，不可控）。

    :param ext_whitelist: 允许的扩展名集合（音频/图片白名单）
    :param ext_hint: 调用方提供的扩展名（会经白名单校验），非法时从 URL 推断
    :return: 本地路径，失败返回 None
    """
    result = await _safe_fetch_bytes(session, url, max_bytes)
    if result is None:
        return None
    data, content_type = result

    # 扩展名：优先调用方提示（白名单内），否则从 URL 推断，最后按 Content-Type 兜底
    ext = ""
    if ext_hint.startswith(".") and ext_hint in ext_whitelist:
        ext = ext_hint
    if not ext:
        url_path = urllib.parse.urlparse(url).path
        _, ext = os.path.splitext(url_path)
        if ext not in ext_whitelist:
            ext = _guess_voice_ext(url, content_type) if ext_whitelist is AUDIO_EXT_WHITELIST else ""
    if not ext:
        ext = ".silk" if ext_whitelist is AUDIO_EXT_WHITELIST else ".jpg"

    os.makedirs(cache_dir, exist_ok=True)
    tmp_path = os.path.join(cache_dir, f"{hash(url)}{ext}")
    with open(tmp_path, "wb") as f:
        f.write(data)
    return tmp_path


def _is_safe_local_ref(path: str) -> bool:
    """
    校验本地文件引用是否安全：仅接受无路径穿越的裸文件名（相对路径）。
    拒绝绝对路径（防任意本地文件读取）与含 .. 的路径。
    """
    if not path:
        return False
    if os.path.isabs(path):
        return False
    if ".." in path.replace("\\", "/").split("/"):
        return False
    return True


async def download_voice_file(bot: Bot, file_id: str, cache_dir: str = VOICE_CACHE_DIR) -> Optional[str]:
    """
    下载 QQ 语音文件到本地临时文件
    参数 file_id: 优先使用 HTTP URL；其次尝试本地路径；最后通过 OneBot API 解析
    返回本地路径，失败返回 None
    """
    try:
        # ── 路径 1：HTTP(S) URL → 安全下载 ──
        if file_id.startswith("http://") or file_id.startswith("https://"):
            async with aiohttp.ClientSession() as session:
                # 从 URL 或 Content-Type 推断扩展名
                tmp_path = await _safe_download_and_save(
                    session, file_id, cache_dir, VOICE_MAX_DOWNLOAD_BYTES,
                    ext_whitelist=AUDIO_EXT_WHITELIST,
                )
                if tmp_path:
                    logger.debug(f"语音文件已下载 (HTTP): {tmp_path}")
                    return tmp_path
                return None

        # ── 路径 2：本地裸文件名（如 "abc123.silk"）已存在 → 直接返回 ──
        # 仅接受无路径穿越的相对引用，拒绝绝对路径与 ../，防止任意本地文件读取
        if _is_safe_local_ref(file_id) and os.path.exists(file_id):
            return file_id

        # ── 路径 3：文件引用 → 通过 OneBot API 解析 ──
        try:
            # go-cqhttp / Lagrange / NapCat 等实现支持 get_record
            record_info = await bot.call_api('get_record', **{'file': file_id})
            if isinstance(record_info, dict):
                # 优先使用 API 返回的 URL
                url = record_info.get('url', '')
                if url and (url.startswith("http://") or url.startswith("https://")):
                    async with aiohttp.ClientSession() as session:
                        tmp_path = await _safe_download_and_save(
                            session, url, cache_dir, VOICE_MAX_DOWNLOAD_BYTES,
                            ext_whitelist=AUDIO_EXT_WHITELIST,
                        )
                        if tmp_path:
                            logger.debug(f"语音文件已下载 (API→HTTP): {tmp_path}")
                            return tmp_path
                # 尝试 API 返回的本地路径（协议端返回，视为可信；仍拒绝穿越路径）
                path = record_info.get('path', '') or record_info.get('file', '')
                if path and _is_safe_local_ref(path) and os.path.exists(path):
                    return path
        except Exception as e:
            logger.debug(f"get_record API 调用失败: {e}")

        logger.warning(f"无法解析语音文件引用: {file_id}")
        return None

    except Exception as e:
        logger.error(f"下载语音文件失败: {e}")
        return None


def _guess_voice_ext(url: str, content_type: str) -> str:
    """根据 URL 或 Content-Type 推断语音文件扩展名"""
    # 从 URL 中提取扩展名
    url_path = url.split("?")[0]
    _, ext = os.path.splitext(url_path)
    if ext in (".silk", ".amr", ".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".spx"):
        return ext
    # 从 Content-Type 推断
    ct_map = {
        "audio/amr": ".amr",
        "audio/wav": ".wav", "audio/wave": ".wav",
        "audio/mpeg": ".mp3", "audio/mp3": ".mp3",
        "audio/ogg": ".ogg", "audio/opus": ".ogg",
        "audio/aac": ".aac",
        "audio/flac": ".flac",
    }
    for ct_key, ext in ct_map.items():
        if ct_key in content_type:
            return ext
    # 默认 silk（QQ 语音最常见格式）
    return ".silk"


def silk_to_wav(silk_path: str, wav_path: str) -> bool:
    """
    将 silk v3 格式转换为 wav 格式

    使用 pilk 库进行解码。若 pilk 不可用，尝试使用系统 ffmpeg。
    返回 True 表示转换成功，False 表示失败。
    """
    # 优先使用 pilk（纯 Python silk v3 编解码）
    try:
        import pilk
        from .config import plugin_config

        with open(silk_path, "rb") as f:
            silk_data = f.read()

        # pilk.decode 返回 (sample_rate, pcm_data)
        sample_rate, pcm_data = pilk.decode(silk_data)

        # 将 PCM 16-bit 写入 wav 文件
        import struct
        import wave

        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_data)

        logger.info(f"silk→wav 转换成功 (pilk): {silk_path} → {wav_path}")
        return True

    except ImportError:
        logger.debug("pilk 未安装，尝试使用 ffmpeg 转换 silk")

    # 降级方案：使用 ffmpeg（需要系统安装 ffmpeg）
    try:
        import subprocess
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", silk_path, "-acodec", "pcm_s16le",
             "-ar", "16000", "-ac", "1", wav_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            logger.info(f"silk→wav 转换成功 (ffmpeg): {silk_path} → {wav_path}")
            return True
        else:
            logger.error(f"ffmpeg 转换失败: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"silk→wav 转换失败: {e}")
        logger.warning("请安装 pilk (pip install pilk) 或将 ffmpeg 添加到系统 PATH")
        return False


def audio_to_qq_voice(audio_np, sample_rate: int) -> MessageSegment:
    """
    将 numpy 音频数组转换为 QQ 语音消息段。
    临时文件会在 Bot 发送后由调用方清理，或留待下次启动时统一清理。
    """
    import uuid
    os.makedirs(VOICE_CACHE_DIR, exist_ok=True)
    tmp_wav = os.path.join(VOICE_CACHE_DIR, f"tts_{uuid.uuid4().hex[:12]}.wav")
    import soundfile as sf
    sf.write(tmp_wav, audio_np, sample_rate)
    # 必须使用绝对路径，OneBot 客户端（NapCat/Lagrange）无法解析相对路径
    abs_path = os.path.abspath(tmp_wav)
    return MessageSegment.record(f"file:///{abs_path}")


async def download_image_file(bot: Bot, url: str, file_id: str,
                               cache_dir: str = "image_cache") -> Optional[str]:
    """
    下载 QQ 图片文件到本地临时文件
    返回本地路径，失败返回 None
    """
    try:
        if url.startswith(("http://", "https://")):
            async with aiohttp.ClientSession() as session:
                # 安全下载：SSRF 校验 + 大小限制 + 超时；文件名基于 URL 哈希
                tmp_path = await _safe_download_and_save(
                    session, url, cache_dir, IMAGE_MAX_DOWNLOAD_BYTES,
                    ext_whitelist=IMAGE_EXT_WHITELIST,
                )
                return tmp_path
        else:
            # 本地路径：仅接受无路径穿越的相对引用（与语音下载一致）
            if _is_safe_local_ref(url) and os.path.exists(url):
                return url
            logger.warning(f"[下载安全] 拒绝本地路径引用: {url}")
            return None
    except Exception as e:
        logger.error(f"下载图片文件失败: {e}")
    return None