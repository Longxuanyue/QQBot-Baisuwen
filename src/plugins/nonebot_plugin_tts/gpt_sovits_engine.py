"""
GPT-SoVITS 语音合成引擎，实现 BaseTTSEngine 接口。

集成策略3情感路由：根据 LLM 回复内容自动选择最合适的角色音色。

依赖: GPT-SoVITS 已安装于 D:/GPT-SoVITS-main，pip 依赖已安装。
"""

import os
import sys
import gc
import logging
import time
from typing import Optional

import numpy as np
import torch

# 抑制 torchaudio FFmpeg 扩展缺失的 DEBUG 噪音（不影响功能，librosa/soundfile 可替代）
# C++ 层日志通过环境变量控制
if "TORCH_CPP_LOG_LEVEL" not in os.environ:
    os.environ["TORCH_CPP_LOG_LEVEL"] = "ERROR"
if "TORCH_LOGS" not in os.environ:
    os.environ["TORCH_LOGS"] = "ERROR"

from .config import GPT_SOVITS_CONFIG, GPT_SOVITS_DEFAULT_CHARACTER, GPT_SOVITS_ROOT as _GPT_SOVITS_ROOT
from .ref_audio_index import ReferenceAudioIndex
from .character_router import CharacterRouter

# ── 导入 GPT-SoVITS 核心模块 ──
# GPT-SoVITS 代码内部多处使用 os.getcwd() 拼接相对路径，
# 需要临时切换到 GPT-SoVITS 根目录进行导入和初始化（根目录由 .env 的 GPT_SOVITS_ROOT 控制）。
_GPT_SOVITS_MODULE = os.path.join(_GPT_SOVITS_ROOT, "GPT_SoVITS")

_original_cwd = os.getcwd()


def _setup_gpt_sovits_path():
    """设置 GPT-SoVITS 所需的 sys.path 和工作目录"""
    # 添加 GPT_SoVITS 子目录到 sys.path
    for p in [_GPT_SOVITS_MODULE, _GPT_SOVITS_ROOT]:
        if p not in sys.path:
            sys.path.insert(0, p)
    # 切换工作目录
    os.chdir(_GPT_SOVITS_ROOT)


def _restore_cwd():
    """恢复原始工作目录"""
    try:
        os.chdir(_original_cwd)
    except OSError:
        pass  # 原始目录可能已被删除


def _get_tts_config_path() -> str:
    """获取 tts_infer.yaml 的完整路径"""
    if GPT_SOVITS_CONFIG and os.path.exists(GPT_SOVITS_CONFIG):
        return GPT_SOVITS_CONFIG
    default = os.path.join(_GPT_SOVITS_MODULE, "configs", "tts_infer.yaml")
    return default


class GPTSoVITSEngine:
    """
    GPT-SoVITS 语音合成引擎。

    使用方式:
        engine = GPTSoVITSEngine()
        sr, audio = engine.synthesize("你好世界")
        engine.close()
    """

    def __init__(
        self,
        gpt_sovits_config: Optional[str] = None,
        default_character: Optional[str] = None,
        sentiment_analyzer=None,
        version: str = "v2",
        device: Optional[str] = None,
        is_half: bool = True,
        t2s_weights_path: Optional[str] = None,
        vits_weights_path: Optional[str] = None,
    ):
        """
        :param gpt_sovits_config: tts_infer.yaml 路径，None 使用默认
        :param default_character: 默认角色名
        :param sentiment_analyzer: 情感分析器实例（用于策略3）
        :param version: GPT-SoVITS 版本: v1/v2/v3/v4/v2Pro/v2ProPlus
        :param device: 推理设备 (cuda/cuda:0/cpu)，None 自动检测
        :param is_half: 是否使用 fp16
        :param t2s_weights_path: GPT 权重路径（训练好的），None 用 yaml 默认
        :param vits_weights_path: SoVITS 权重路径（训练好的），None 用 yaml 默认
        """
        self._config_path = gpt_sovits_config or _get_tts_config_path()
        self._default_character = default_character or GPT_SOVITS_DEFAULT_CHARACTER
        self._version = version
        self._device_str = device or ("cuda:0" if torch.cuda.is_available() else "cpu")
        self._is_half = is_half and self._device_str != "cpu"
        self._t2s_weights = t2s_weights_path
        self._vits_weights = vits_weights_path

        print(f"[GPT-SoVITS] Initializing engine (version={version}, device={self._device_str})")

        # 1. 设置路径并导入 GPT-SoVITS
        _setup_gpt_sovits_path()
        try:
            from GPT_SoVITS.TTS_infer_pack.TTS import TTS, TTS_Config
            self._TTS = TTS
            self._TTS_Config = TTS_Config
        finally:
            _restore_cwd()

        # 2. 加载配置
        print(f"[GPT-SoVITS] Loading config from {self._config_path}")
        self._tts_config = self._TTS_Config(self._config_path)
        # 覆盖版本和设备
        self._tts_config.version = self._version
        self._tts_config.device = torch.device(self._device_str)
        self._tts_config.is_half = self._is_half
        # 覆盖权重路径（使用训练好的模型 > yaml 默认 > fallback）
        if self._t2s_weights:
            self._tts_config.t2s_weights_path = self._t2s_weights
            print(f"[GPT-SoVITS] GPT weights override: {self._t2s_weights}")
        if self._vits_weights:
            self._tts_config.vits_weights_path = self._vits_weights
            print(f"[GPT-SoVITS] SoVITS weights override: {self._vits_weights}")

        # 3. 初始化 TTS 模型（需要正确的 cwd）
        _setup_gpt_sovits_path()
        try:
            print("[GPT-SoVITS] Loading models (this may take 30-60s on first run)...")
            t0 = time.perf_counter()
            self._tts = self._TTS(self._tts_config)
            print(f"[GPT-SoVITS] Models loaded in {time.perf_counter() - t0:.1f}s")
        finally:
            _restore_cwd()

        # 4. 加载参考音频索引
        print("[GPT-SoVITS] Loading reference audio index...")
        self._ref_index = ReferenceAudioIndex()

        # 5. 创建角色路由器
        self._router = CharacterRouter(
            index=self._ref_index,
            default_character=self._default_character,
            sentiment_analyzer=sentiment_analyzer,
        )
        print(f"[GPT-SoVITS] Router ready: default={self._default_character}, "
              f"available={len(self._ref_index.characters)} characters")

        self._sample_rate = self._tts_config.sampling_rate
        self._ready = True

        # 预热：路由一个短文本触发索引加载
        _ = self._router.get_available_characters()

    @property
    def name(self) -> str:
        return "gpt_sovits"

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def is_available(self) -> bool:
        return self._ready and self._tts is not None

    def synthesize(
        self,
        text: str,
        speed: Optional[float] = None,
        noise_scale: Optional[float] = None,
        noise_scale_w: Optional[float] = None,
    ) -> tuple:
        """
        合成语音。

        :param text: 待合成文本
        :param speed: 语速（>1 加快，<1 减慢），映射为 speed_factor
        :param noise_scale: 未使用
        :param noise_scale_w: 未使用
        :return: (sample_rate: int, audio: np.ndarray)
        """
        if not self._ready:
            raise RuntimeError("GPT-SoVITS engine not initialized")
        if not text or not text.strip():
            raise ValueError("Text is empty")

        # 1. 策略3路由：选择角色和参考音频
        char_name, ref_slice = self._router.route(text)
        ref_audio_path = ref_slice["path"]
        prompt_text = ref_slice["text"]
        prompt_lang = ref_slice.get("lang", "zh")

        print(f"[GPT-SoVITS] Route: '{text[:30]}...' -> {char_name} "
              f"(ref: {os.path.basename(ref_audio_path)})")

        # 2. 速度映射
        speed_factor = 1.0 / speed if speed and speed > 0 else 1.0

        # prompt_lang 统一转小写（.list 文件中是 "ZH" 大写）
        prompt_lang = prompt_lang.lower()

        # 3. 整个推理过程保持 cwd 在 GPT-SoVITS 根目录
        _setup_gpt_sovits_path()
        try:
            # 设置参考音频
            self._tts.set_ref_audio(ref_audio_path)

            # 捕获 stderr 以便在出错时获取 GPT-SoVITS 内部 traceback
            import io
            stderr_capture = io.StringIO()
            old_stderr = sys.stderr
            sys.stderr = stderr_capture

            try:
                result_sr = None
                result_audio = None
                error_occurred = False

                gen = self._tts.run({
                    "text": text,
                    "text_lang": "zh",
                    "ref_audio_path": ref_audio_path,
                    "prompt_text": prompt_text,
                    "prompt_lang": prompt_lang,
                    "speed_factor": speed_factor,
                    "top_k": 15,
                    "top_p": 1.0,
                    "temperature": 1.0,
                    "text_split_method": "cut1",
                    "batch_size": 1,
                    "parallel_infer": True,
                    "streaming_mode": False,
                    "return_fragment": False,
                    "seed": -1,
                    "repetition_penalty": 1.35,
                })

                for item in gen:
                    if isinstance(item, tuple) and len(item) == 2:
                        item_sr, item_audio = item
                        # 检测错误信号：GPT-SoVITS 内部异常时 yield 16000Hz 空音频
                        if item_sr == 16000 and self._tts_config.sampling_rate != 16000:
                            stderr_output = stderr_capture.getvalue()
                            if stderr_output.strip():
                                print(f"[GPT-SoVITS] Internal error detected:\n{stderr_output[-2000:]}")
                            error_occurred = True
                            continue  # 跳过错误信号，继续等待可能的重试
                        result_sr, result_audio = item_sr, item_audio

            finally:
                sys.stderr = old_stderr
                stderr_output = stderr_capture.getvalue()
                if stderr_output.strip():
                    # 只在有错误时打印 stderr（正常情况无 stderr 输出）
                    lines = stderr_output.strip().split("\n")
                    # 过滤掉 DEBUG 级别的 torch 日志
                    errors = [l for l in lines if "DEBUG" not in l and "Traceback" not in l or "Error" in l or "error" in l]
                    if errors or "Traceback" in stderr_output:
                        print(f"[GPT-SoVITS] stderr output:\n{stderr_output[-3000:]}")

            if error_occurred and result_audio is None:
                raise RuntimeError(
                    f"GPT-SoVITS inference failed internally. "
                    f"stderr tail: {stderr_output[-500:]}"
                )

            if result_audio is None:
                raise RuntimeError("GPT-SoVITS inference produced no output")

            # 确保是 float32 numpy array
            if isinstance(result_audio, np.ndarray):
                if result_audio.dtype == np.int16:
                    result_audio = result_audio.astype(np.float32) / 32768.0
            else:
                result_audio = np.array(result_audio, dtype=np.float32)

            return (result_sr, result_audio)

        except Exception as e:
            import traceback as tb
            full_tb = tb.format_exc()
            # 只打印最后 2000 字符，避免日志爆炸
            print(f"[GPT-SoVITS] Synthesis error: {e}\n{full_tb[-2000:]}")
            raise RuntimeError(f"GPT-SoVITS synthesis failed: {e}\n{full_tb[-1000:]}") from e

        finally:
            _restore_cwd()

    def close(self):
        """释放 GPU 显存"""
        self._ready = False
        if hasattr(self, "_tts") and self._tts is not None:
            del self._tts
            self._tts = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print("[GPT-SoVITS] Engine closed, GPU memory freed")

    def get_router(self) -> CharacterRouter:
        """获取角色路由器实例（供外部查询）"""
        return self._router

    def __repr__(self):
        return (f"<GPTSoVITSEngine version={self._version} "
                f"device={self._device_str} "
                f"default={self._default_character}>")
