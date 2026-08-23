"""
ASR 配置：模型参数、设备等由 .env 驱动；音频参数为技术常量保持不变。
"""

import os
from pathlib import Path

import torch


# ── 显式加载 .env，避免因插件导入顺序导致配置为空 ──
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=False)
except ImportError:
    pass


# 模型默认配置（环境变量可覆盖）
DEFAULT_MODEL_SIZE = os.getenv("ASR_MODEL_SIZE", "small")  # 可选: tiny, base, small, medium, large
DEFAULT_LANGUAGE = os.getenv("ASR_LANGUAGE", "zh")         # 识别语言，None 表示自动检测
DEFAULT_DEVICE = os.getenv("ASR_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")

# 音频参数（Whisper 内部会重采样，输入任意采样率均可）——技术常量，不随 .env 变
SAMPLE_RATE = 16000

# 录音参数（用于辅助函数）
RECORD_SAMPLE_RATE = 16000
RECORD_CHANNELS = 1
RECORD_DTYPE = "float32"
SILENCE_THRESHOLD = 0.01           # 静音阈值（幅度）
SILENCE_DURATION = 1.0             # 静音持续多少秒后停止录音（秒）
MAX_RECORD_SECONDS = 30            # 最大录音时长
