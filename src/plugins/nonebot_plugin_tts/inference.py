import sys
import os
import torch
import numpy as np
from torch import LongTensor, no_grad

# 从当前包的 vits 子目录导入
from .vits import utils, commons
from .vits.models import SynthesizerTrn
from .vits.text import text_to_sequence

from .config import (
    DEFAULT_MODEL_PATH, DEFAULT_CONFIG_PATH,
    DEFAULT_SPEED, DEFAULT_NOISE_SCALE, DEFAULT_NOISE_SCALE_W,
    DEVICE, LANGUAGE_MARK
)
from .exceptions import ModelLoadError, SynthesisError

class TTSInference:
    def __init__(self, model_path=None, config_path=None, device=None):
        self.model_path = model_path or DEFAULT_MODEL_PATH
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.device = device or DEVICE

        if not os.path.exists(self.model_path):
            raise ModelLoadError(f"模型文件不存在: {self.model_path}")
        if not os.path.exists(self.config_path):
            raise ModelLoadError(f"配置文件不存在: {self.config_path}")

        self.hps = utils.get_hparams_from_file(self.config_path)

        self.net_g = SynthesizerTrn(
            len(self.hps.symbols),
            self.hps.data.filter_length // 2 + 1,
            self.hps.train.segment_size // self.hps.data.hop_length,
            n_speakers=self.hps.data.n_speakers,
            **self.hps.model
        ).to(self.device)
        self.net_g.eval()
        utils.load_checkpoint(self.model_path, self.net_g, None)

        self.speaker_ids = self.hps.speakers
        self.speaker_id = list(self.speaker_ids.values())[0] if self.speaker_ids else 0
        self.sample_rate = self.hps.data.sampling_rate

        print(f"TTS 模型加载成功 | 设备: {self.device} | 说话人: {list(self.speaker_ids.keys())}")

    def _get_text_tensor(self, text):
        text = f"{LANGUAGE_MARK}{text}{LANGUAGE_MARK}"
        text_norm = text_to_sequence(text, self.hps.symbols, self.hps.data.text_cleaners)
        if self.hps.data.add_blank:
            text_norm = commons.intersperse(text_norm, 0)
        text_norm = LongTensor(text_norm)
        return text_norm

    def synthesize(self, text, speed=None, noise_scale=None, noise_scale_w=None):
        speed = speed if speed is not None else DEFAULT_SPEED
        noise_scale = noise_scale if noise_scale is not None else DEFAULT_NOISE_SCALE
        noise_scale_w = noise_scale_w if noise_scale_w is not None else DEFAULT_NOISE_SCALE_W

        if not text or not text.strip():
            raise SynthesisError("文本为空")

        try:
            stn_tst = self._get_text_tensor(text)
            with no_grad():
                x_tst = stn_tst.unsqueeze(0).to(self.device)
                x_tst_lengths = LongTensor([stn_tst.size(0)]).to(self.device)
                sid = LongTensor([self.speaker_id]).to(self.device)
                audio = self.net_g.infer(
                    x_tst, x_tst_lengths,
                    sid=sid,
                    noise_scale=noise_scale,
                    noise_scale_w=noise_scale_w,
                    length_scale=1.0 / speed
                )[0][0, 0].data.cpu().float().numpy()
            return self.sample_rate, audio
        except Exception as e:
            raise SynthesisError(f"合成失败: {e}")

    def close(self):
        del self.net_g
        torch.cuda.empty_cache()

def load_model(model_path=None, config_path=None, device=None):
    return TTSInference(model_path, config_path, device)