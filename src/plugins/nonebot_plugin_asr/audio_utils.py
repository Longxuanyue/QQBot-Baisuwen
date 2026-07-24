"""
音频录制辅助工具：录音、静音检测等
依赖 sounddevice 和 numpy
"""

import numpy as np
import sounddevice as sd
import time

from .config import (
    RECORD_SAMPLE_RATE, RECORD_CHANNELS, RECORD_DTYPE,
    SILENCE_THRESHOLD, SILENCE_DURATION, MAX_RECORD_SECONDS
)
from .exceptions import AudioInputError

def record_audio(duration, samplerate=RECORD_SAMPLE_RATE):
    """
    录制固定时长的音频
    :param duration: 时长（秒）
    :param samplerate: 采样率
    :return: numpy 数组 (float32, 范围 [-1, 1])
    """
    audio = sd.rec(int(duration * samplerate), samplerate=samplerate,
                   channels=RECORD_CHANNELS, dtype=RECORD_DTYPE)
    sd.wait()
    return audio.flatten()

def record_until_silence(
    samplerate=RECORD_SAMPLE_RATE,
    silence_threshold=SILENCE_THRESHOLD,
    silence_duration=SILENCE_DURATION,
    max_duration=MAX_RECORD_SECONDS,
    start_quiet_seconds=0.5
):
    """
    录音直到检测到静音（适合语音交互）
    :param samplerate: 采样率
    :param silence_threshold: 静音幅度阈值（低于此值视为静音）
    :param silence_duration: 连续静音持续多少秒后停止录音
    :param max_duration: 最大录音时长（秒）
    :param start_quiet_seconds: 开始录音时忽略前多少秒的静音（避免刚启动时误判）
    :return: numpy 数组 (float32)
    """
    print("开始录音...")
    audio_buffer = []
    silent_chunks = 0
    chunk_duration = 0.1               # 每次检测块长 0.1 秒
    chunk_samples = int(samplerate * chunk_duration)
    required_silent_chunks = int(silence_duration / chunk_duration)
    started = False                    # 是否已开始检测到声音
    start_time = time.time()

    with sd.InputStream(samplerate=samplerate, channels=1, dtype=RECORD_DTYPE) as stream:
        while True:
            if time.time() - start_time > max_duration:
                print("达到最大录音时长，停止录音")
                break
            data, _ = stream.read(chunk_samples)
            audio_chunk = data.flatten()
            audio_buffer.extend(audio_chunk)
            # 计算当前块的最大幅度
            max_amp = np.max(np.abs(audio_chunk))
            if max_amp > silence_threshold:
                if not started:
                    started = True
                silent_chunks = 0
            else:
                if started:
                    silent_chunks += 1
                else:
                    # 还未开始，不累计静音（跳过起始静音）
                    pass
            if started and silent_chunks >= required_silent_chunks:
                print("检测到静音，停止录音")
                break

    audio = np.array(audio_buffer, dtype=np.float32)
    # 可选：去除首尾微小静音
    return audio

# 可选：保存音频到文件
def save_audio(audio_np, file_path, samplerate=RECORD_SAMPLE_RATE):
    import soundfile as sf
    sf.write(file_path, audio_np, samplerate)