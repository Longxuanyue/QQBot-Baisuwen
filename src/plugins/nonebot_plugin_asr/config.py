"""
配置常量：模型参数、设备、音频参数等
"""

import torch

# 模型默认配置
DEFAULT_MODEL_SIZE = "small"      # 可选: tiny, base, small, medium, large
DEFAULT_LANGUAGE = "zh"            # 识别语言，None 表示自动检测
DEFAULT_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# 音频参数（Whisper 内部会重采样，输入任意采样率均可）
SAMPLE_RATE = 16000                # Whisper 内部使用 16000 Hz

# 录音参数（用于辅助函数）
RECORD_SAMPLE_RATE = 16000
RECORD_CHANNELS = 1
RECORD_DTYPE = "float32"
SILENCE_THRESHOLD = 0.01           # 静音阈值（幅度）
SILENCE_DURATION = 1.0             # 静音持续多少秒后停止录音（秒）
MAX_RECORD_SECONDS = 30            # 最大录音时长