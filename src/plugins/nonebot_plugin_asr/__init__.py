"""
ASR Module for Local AI Assistant
基于 Whisper 的语音识别模块，支持中文及多语言。
提供简洁的 API：加载模型、识别文件、识别音频数组等。
"""

__version__ = "0.1.1"

from nonebot.plugin import PluginMetadata

from .config import DEFAULT_MODEL_SIZE, DEFAULT_LANGUAGE, DEFAULT_DEVICE, SAMPLE_RATE
from .whisper_asr import WhisperASR, load_model
from .exceptions import ASRError, ModelLoadError, RecognitionError
from .audio_utils import record_audio, record_until_silence

__all__ = [
    "DEFAULT_MODEL_SIZE",
    "DEFAULT_LANGUAGE",
    "DEFAULT_DEVICE",
    "SAMPLE_RATE",
    "WhisperASR",
    "load_model",
    "ASRError",
    "ModelLoadError",
    "RecognitionError",
    "record_audio",
    "record_until_silence",
]

# ── 插件元数据 ──

__plugin_meta__ = PluginMetadata(
    name="语音识别",
    description="基于 OpenAI Whisper 的语音识别模块，支持中文及多语言",
    usage="内部 library 插件，无直接用户命令；为其他插件提供 ASR 能力",
    type="library",
    homepage="https://github.com/baisuwen",
    supported_adapters={"~onebot.v11"},
    extra={
        "author": "baisuwen",
        "version": __version__,
    },
)