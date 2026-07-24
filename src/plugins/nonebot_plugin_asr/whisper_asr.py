"""
Whisper ASR 核心封装
"""

import whisper
import torch
import numpy as np
import tempfile
import os
import soundfile as sf

from .config import DEFAULT_MODEL_SIZE, DEFAULT_LANGUAGE, DEFAULT_DEVICE
from .exceptions import ModelLoadError, RecognitionError, AudioInputError

class WhisperASR:
    """Whisper 语音识别封装类（单例模式推荐）"""

    def __init__(self, model_size=None, device=None, language=None):
        """
        初始化 Whisper 模型
        :param model_size: 模型大小，默认 config.DEFAULT_MODEL_SIZE
        :param device: 设备（cuda/cpu），默认自动选择
        :param language: 识别语言代码（如 'zh'），默认中文
        """
        self.model_size = model_size or DEFAULT_MODEL_SIZE
        self.device = device or DEFAULT_DEVICE
        self.language = language or DEFAULT_LANGUAGE

        try:
            self.model = whisper.load_model(self.model_size, device=self.device)
        except Exception as e:
            raise ModelLoadError(f"加载 Whisper 模型失败 ({self.model_size}): {e}")

        print(f"ASR 模型加载成功 | 模型: {self.model_size} | 设备: {self.device} | 语言: {self.language}")

    def transcribe_file(self, audio_path, language=None, **kwargs):
        """
        识别音频文件
        :param audio_path: 音频文件路径（支持 wav, mp3, m4a 等）
        :param language: 语言代码，覆盖初始化设置
        :param kwargs: 其他 whisper.transcribe 参数（如 temperature, vad_filter 等）
        :return: 识别文本字符串
        """
        if not os.path.exists(audio_path):
            raise AudioInputError(f"音频文件不存在: {audio_path}")

        lang = language or self.language
        try:
            result = self.model.transcribe(audio_path, language=lang, **kwargs)
            return result["text"].strip()
        except Exception as e:
            raise RecognitionError(f"识别失败: {e}")

    def transcribe_audio_array(self, audio_np, sample_rate, language=None, **kwargs):
        """
        识别 numpy 音频数组
        :param audio_np: numpy 数组，形状 (N,) 或 (N, C)，值范围 [-1, 1] 或 int16
        :param sample_rate: 原始采样率
        :param language: 语言代码
        :param kwargs: 其他 whisper.transcribe 参数
        :return: 识别文本字符串
        """
        if audio_np is None or len(audio_np) == 0:
            raise AudioInputError("音频数组为空")

        # 转换为 float32 并归一化（如果还未归一化）
        if audio_np.dtype == np.int16:
            audio_np = audio_np.astype(np.float32) / 32768.0
        elif audio_np.dtype == np.int32:
            audio_np = audio_np.astype(np.float32) / 2147483648.0
        else:
            audio_np = audio_np.astype(np.float32)

        # 如果是多声道，取平均
        if len(audio_np.shape) > 1:
            audio_np = np.mean(audio_np, axis=1)

        # 保存为临时 WAV 文件（Whisper 需要文件路径）
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name
        try:
            sf.write(temp_path, audio_np, sample_rate)
            text = self.transcribe_file(temp_path, language=language, **kwargs)
            return text
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def close(self):
        """释放模型显存（可选）"""
        del self.model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

# 便捷函数
def load_model(model_size=None, device=None, language=None):
    """加载模型并返回 WhisperASR 实例"""
    return WhisperASR(model_size, device, language)