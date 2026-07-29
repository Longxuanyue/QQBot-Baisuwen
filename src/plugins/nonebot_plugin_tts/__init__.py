"""
nonebot_plugin_tts - 文本转语音插件

支持 VITS（默认）和 GPT-SoVITS 双引擎，多角色音色切换。
"""

__version__ = "1.0.2"

from nonebot.plugin import PluginMetadata

from .config import DEFAULT_SPEED, DEFAULT_NOISE_SCALE, DEFAULT_NOISE_SCALE_W, SAMPLE_RATE
from .inference import TTSInference, load_model
from .processing import split_text, concatenate_audio, auto_split_and_synthesize

# GPT-SoVITS 引擎（延迟导入，避免未安装依赖时 import 崩溃）
def _get_gpt_sovits_engine():
    from .gpt_sovits_engine import GPTSoVITSEngine
    return GPTSoVITSEngine

__all__ = [
    "DEFAULT_SPEED",
    "DEFAULT_NOISE_SCALE",
    "DEFAULT_NOISE_SCALE_W",
    "SAMPLE_RATE",
    "TTSInference",
    "load_model",
    "split_text",
    "concatenate_audio",
    "auto_split_and_synthesize",
    "GPTSoVITSEngine",  # 通过 get_gpt_sovits_engine() 获取
    "get_gpt_sovits_engine",
]

# ── 插件元数据 ──

__plugin_meta__ = PluginMetadata(
    name="语音合成",
    description="基于 VITS/GPT-SoVITS 的文本转语音模块，支持双引擎切换与多角色音色",
    usage="内部 library 插件，无直接用户命令；为其他插件提供 TTS 能力",
    type="library",
    homepage="https://github.com/baisuwen",
    supported_adapters={"~onebot.v11"},
    extra={
        "author": "baisuwen",
        "version": __version__,
    },
)

# 兼容直接 import
def __getattr__(name):
    if name == "GPTSoVITSEngine":
        from .gpt_sovits_engine import GPTSoVITSEngine
        return GPTSoVITSEngine
    if name == "get_gpt_sovits_engine":
        return _get_gpt_sovits_engine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")