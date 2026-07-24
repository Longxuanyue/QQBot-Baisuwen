import re
import numpy as np
from .config import MAX_SENTENCE_LEN, SILENCE_MS
from .exceptions import ProcessingError

def split_text(text, max_len=None):
    if max_len is None:
        max_len = MAX_SENTENCE_LEN
    sentences = re.split(r'(?<=[。！？；])', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    result = []
    for sent in sentences:
        if len(sent) <= max_len:
            result.append(sent)
        else:
            sub = re.split(r'(?<=[，、])', sent)
            temp = ""
            for seg in sub:
                if len(temp + seg) <= max_len:
                    temp += seg
                else:
                    if temp:
                        result.append(temp.strip())
                    temp = seg
            if temp:
                result.append(temp.strip())
    return [s for s in result if s]

def concatenate_audio(audio_list, sample_rate, silence_ms=None):
    if silence_ms is None:
        silence_ms = SILENCE_MS
    if not audio_list:
        return np.array([], dtype=np.float32)
    silence = np.zeros(int(sample_rate * silence_ms / 1000), dtype=np.float32)
    result = []
    for audio in audio_list:
        result.append(audio)
        result.append(silence)
    return np.concatenate(result[:-1])

def auto_split_and_synthesize(tts, text, speed=None, noise_scale=None, noise_scale_w=None, silence_ms=None):
    sentences = split_text(text)
    if not sentences:
        raise ProcessingError("拆分后无有效句子")
    audios = []
    sample_rate = None
    for sent in sentences:
        sr, audio = tts.synthesize(sent, speed=speed, noise_scale=noise_scale, noise_scale_w=noise_scale_w)
        if sample_rate is None:
            sample_rate = sr
        audios.append(audio)
    combined = concatenate_audio(audios, sample_rate, silence_ms)
    return sample_rate, combined