import os
from pathlib import Path

# ── 显式加载 .env，避免因插件导入顺序导致配置为空 ──
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(Path(__file__).resolve().parent.parent.parent.parent, ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path, override=False)
except ImportError:
    pass

# 模型与配置文件路径（支持环境变量）
DEFAULT_MODEL_PATH = os.getenv("TTS_MODEL_PATH", "models/G_latest.pth")
DEFAULT_CONFIG_PATH = os.getenv("TTS_CONFIG_PATH", "models/finetune_speaker.json")

# GPT-SoVITS 配置
GPT_SOVITS_CONFIG = os.getenv(
    "GPT_SOVITS_CONFIG",
    "D:/GPT-SoVITS-main/GPT_SoVITS/configs/tts_infer.yaml"
)
GPT_SOVITS_VERSION = os.getenv("GPT_SOVITS_VERSION", "v2")
GPT_SOVITS_DEFAULT_CHARACTER = os.getenv("GPT_SOVITS_DEFAULT_CHARACTER", "陈千语")
GPT_SOVITS_DEVICE = os.getenv("GPT_SOVITS_DEVICE", "cuda:0")
GPT_SOVITS_IS_HALF = os.getenv("GPT_SOVITS_IS_HALF", "true").lower() == "true"

# 推理默认参数
DEFAULT_SPEED = float(os.getenv("TTS_SPEED", "1.0"))
DEFAULT_NOISE_SCALE = float(os.getenv("TTS_NOISE_SCALE", "0.667"))
DEFAULT_NOISE_SCALE_W = float(os.getenv("TTS_NOISE_SCALE_W", "0.8"))

# 音频参数
SAMPLE_RATE = 22050

# 文本处理
MAX_SENTENCE_LEN = int(os.getenv("TTS_MAX_SENTENCE_LEN", "50"))
SILENCE_MS = int(os.getenv("TTS_SILENCE_MS", "300"))

# 语言标记
LANGUAGE_MARK = "[ZH]"

# 设备（自动选择，也可手动指定）
DEVICE = os.getenv("TTS_DEVICE", "cuda:0" if __import__("torch").cuda.is_available() else "cpu")