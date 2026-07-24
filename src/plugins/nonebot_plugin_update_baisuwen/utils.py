import os
import tempfile
import aiohttp
from typing import Optional
from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, MessageSegment

# 语音文件缓存目录
VOICE_CACHE_DIR = "voice_cache"

async def download_voice_file(bot: Bot, file_id: str, cache_dir: str = VOICE_CACHE_DIR) -> Optional[str]:
    """
    下载 QQ 语音文件到本地临时文件
    参数 file_id: 优先使用 HTTP URL；其次尝试本地路径；最后通过 OneBot API 解析
    返回本地路径，失败返回 None
    """
    try:
        # ── 路径 1：HTTP(S) URL → 直接下载 ──
        if file_id.startswith("http://") or file_id.startswith("https://"):
            async with aiohttp.ClientSession() as session:
                async with session.get(file_id) as resp:
                    if resp.status == 200:
                        os.makedirs(cache_dir, exist_ok=True)
                        # 从 URL 或 Content-Type 推断扩展名
                        ext = _guess_voice_ext(file_id, resp.headers.get("Content-Type", ""))
                        tmp_path = os.path.join(cache_dir, f"{hash(file_id)}{ext}")
                        with open(tmp_path, "wb") as f:
                            f.write(await resp.read())
                        logger.debug(f"语音文件已下载 (HTTP): {tmp_path}")
                        return tmp_path
                    else:
                        logger.warning(f"下载语音文件 HTTP {resp.status}: {file_id}")
                        return None

        # ── 路径 2：本地文件已存在 → 直接返回 ──
        if os.path.exists(file_id):
            return file_id

        # ── 路径 3：文件引用（如 "abc123.silk"）→ 通过 OneBot API 解析 ──
        try:
            # go-cqhttp / Lagrange / NapCat 等实现支持 get_record
            record_info = await bot.call_api('get_record', **{'file': file_id})
            if isinstance(record_info, dict):
                # 优先使用 API 返回的 URL
                url = record_info.get('url', '')
                if url:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                os.makedirs(cache_dir, exist_ok=True)
                                ext = _guess_voice_ext(url, resp.headers.get("Content-Type", ""))
                                tmp_path = os.path.join(cache_dir, f"{hash(url)}{ext}")
                                with open(tmp_path, "wb") as f:
                                    f.write(await resp.read())
                                logger.debug(f"语音文件已下载 (API→HTTP): {tmp_path}")
                                return tmp_path
                # 尝试 API 返回的本地路径
                path = record_info.get('path', '') or record_info.get('file', '')
                if path and os.path.exists(path):
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
        os.makedirs(cache_dir, exist_ok=True)
        if url.startswith("http"):
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
                        tmp_path = os.path.join(cache_dir, f"{hash(file_id)}{ext}")
                        with open(tmp_path, "wb") as f:
                            f.write(await resp.read())
                        return tmp_path
        else:
            if os.path.exists(url):
                return url
    except Exception as e:
        logger.error(f"下载图片文件失败: {e}")
    return None