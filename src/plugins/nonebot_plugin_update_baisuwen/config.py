"""
统一配置管理：使用 Pydantic BaseSettings 从 .env 加载所有配置。
采用分组模型组织配置项，同时保持向后兼容（所有旧 .env 键名不变）。
"""

import os
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（baisuwen/），.env 文件所在位置
# 路径推导：config.py → update_baisuwen/ → plugins/ → src/ → baisuwen/
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

# 显式加载 .env 到 os.environ，确保嵌套 BaseModel 的 _fallback_to_os_environ
# 验证器能通过 os.getenv() 读取到配置值（pydantic-settings 不会自动将
# .env 内容注入嵌套 BaseModel，也不会默认写入 os.environ）
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path, override=False)
except ImportError:
    pass  # python-dotenv 不可用时退化到仅依赖 pydantic-settings


# ──────────────────────────────────────────────
# 子配置组
# ──────────────────────────────────────────────

class LLMConfig(BaseModel):
    """LLM / DeepSeek 配置"""
    api_key: str = Field("", env="DEEPSEEK_API_KEY")
    api_base: str = Field("https://api.deepseek.com", env="DEEPSEEK_API_BASE")
    model: str = Field("deepseek-v4-pro", env="DEEPSEEK_MODEL")
    timeout: int = Field(60, env="HTTPX_TIMEOUT")
    # ── 优化配置 ──
    # 单次请求上下文预算（token 估算值），超出时按优先级裁剪历史/记忆/画像
    max_context_tokens: int = Field(8192, env="LLM_MAX_CONTEXT_TOKENS")
    # LLM 调用失败重试次数（429/5xx/网络错误时指数退避重试）
    max_retries: int = Field(2, env="LLM_MAX_RETRIES")
    # 重试退避基础间隔（秒），实际等待 = backoff * 2^(attempt-1)
    retry_backoff: float = Field(1.0, env="LLM_RETRY_BACKOFF")
    # 是否启用流式回复（增量发送+删除上一条，体验更流畅；默认关闭）
    stream_reply: bool = Field(False, env="LLM_STREAM_REPLY")
    # 记忆提取最小间隔（秒）：同一用户两次 LLM 记忆提取的最短间隔
    extract_min_interval: int = Field(300, env="MEMORY_EXTRACT_MIN_INTERVAL")
    # 记忆提取专用模型（留空则与主对话使用同一模型）
    extract_model: str = Field("", env="MEMORY_EXTRACT_MODEL")

    @model_validator(mode='after')
    def _fallback_to_os_environ(self):
        """当 pydantic-settings 未能从 .env 加载嵌套模型字段时，
        直接从 os.environ 读取作为后备。"""
        if not self.api_key:
            self.api_key = os.getenv("DEEPSEEK_API_KEY", "")
        if self.api_base == "https://api.deepseek.com":
            env_base = os.getenv("DEEPSEEK_API_BASE", "")
            if env_base:
                self.api_base = env_base
        if self.model == "deepseek-v4-pro":
            env_model = os.getenv("DEEPSEEK_MODEL", "")
            if env_model:
                self.model = env_model

        def _int(key: str, default: int) -> int:
            v = os.getenv(key, "")
            return int(v) if v else default

        def _float(key: str, default: float) -> float:
            v = os.getenv(key, "")
            return float(v) if v else default

        def _bool(key: str, default: bool) -> bool:
            v = os.getenv(key, "")
            return v.lower() == "true" if v else default

        self.max_context_tokens = _int("LLM_MAX_CONTEXT_TOKENS", self.max_context_tokens)
        self.max_retries = _int("LLM_MAX_RETRIES", self.max_retries)
        self.retry_backoff = _float("LLM_RETRY_BACKOFF", self.retry_backoff)
        self.stream_reply = _bool("LLM_STREAM_REPLY", self.stream_reply)
        self.extract_min_interval = _int("MEMORY_EXTRACT_MIN_INTERVAL", self.extract_min_interval)
        self.extract_model = os.getenv("MEMORY_EXTRACT_MODEL", self.extract_model)
        return self


class ASRConfig(BaseModel):
    """语音识别 (Whisper) 配置"""
    enabled: bool = Field(True, env="ENABLE_ASR")
    model_size: str = Field("small", env="ASR_MODEL_SIZE")
    device: str = Field("cuda", env="ASR_DEVICE")
    language: str = Field("zh", env="ASR_LANGUAGE")

    @model_validator(mode='after')
    def _fallback_to_os_environ(self):
        env_val = os.getenv("ENABLE_ASR", "")
        if env_val:
            self.enabled = env_val.lower() == "true"
        env_val = os.getenv("ASR_MODEL_SIZE", "")
        if env_val:
            self.model_size = env_val
        env_val = os.getenv("ASR_DEVICE", "")
        if env_val:
            self.device = env_val
        env_val = os.getenv("ASR_LANGUAGE", "")
        if env_val:
            self.language = env_val
        return self


class TTSConfig(BaseModel):
    """语音合成配置（VITS / GPT-SoVITS）"""

    # ── 引擎选择 ──
    engine: str = Field("vits", env="TTS_ENGINE")
    # "vits" = 原生 VITS 引擎（默认）
    # "gpt_sovits" = GPT-SoVITS 引擎（策略3情感路由）

    # ── VITS 配置 ──
    enabled: bool = Field(True, env="ENABLE_TTS")
    model_path: str = Field("models/G_latest.pth", env="TTS_MODEL_PATH")
    config_path: str = Field("models/finetune_speaker.json", env="TTS_CONFIG_PATH")
    always: bool = Field(False, env="TTS_ALWAYS")
    speed: float = Field(1.0, env="TTS_SPEED")
    noise_scale: float = Field(0.667, env="TTS_NOISE_SCALE")
    noise_scale_w: float = Field(0.8, env="TTS_NOISE_SCALE_W")
    max_sentence_len: int = Field(50, env="TTS_MAX_SENTENCE_LEN")
    silence_ms: int = Field(300, env="TTS_SILENCE_MS")
    device: str = Field("cuda:0", env="TTS_DEVICE")

    # ── GPT-SoVITS 配置 ──
    gpt_sovits_config: str = Field(
        "D:/GPT-SoVITS-main/GPT_SoVITS/configs/tts_infer.yaml",
        env="GPT_SOVITS_CONFIG"
    )

    @model_validator(mode='after')
    def _fallback_to_os_environ(self):
        """嵌套 BaseModel 的 env 查找可能不生效，直接从 os.environ 后备"""

        def _str(key: str):
            return os.getenv(key, "")

        def _float(key: str, default: float) -> float:
            v = os.getenv(key, "")
            return float(v) if v else default

        def _int(key: str, default: int) -> int:
            v = os.getenv(key, "")
            return int(v) if v else default

        def _bool(key: str, default: bool) -> bool:
            v = os.getenv(key, "")
            return v.lower() == "true" if v else default

        # ── 引擎 ──
        v = _str("TTS_ENGINE")
        if v:
            self.engine = v

        # ── VITS 字段 ──
        self.enabled = _bool("ENABLE_TTS", self.enabled)
        v = _str("TTS_MODEL_PATH")
        if v: self.model_path = v
        v = _str("TTS_CONFIG_PATH")
        if v: self.config_path = v
        self.always = _bool("TTS_ALWAYS", self.always)
        self.speed = _float("TTS_SPEED", self.speed)
        self.noise_scale = _float("TTS_NOISE_SCALE", self.noise_scale)
        self.noise_scale_w = _float("TTS_NOISE_SCALE_W", self.noise_scale_w)
        self.max_sentence_len = _int("TTS_MAX_SENTENCE_LEN", self.max_sentence_len)
        self.silence_ms = _int("TTS_SILENCE_MS", self.silence_ms)
        v = _str("TTS_DEVICE")
        if v: self.device = v

        # ── GPT-SoVITS 字段 ──
        v = _str("GPT_SOVITS_CONFIG")
        if v: self.gpt_sovits_config = v
        v = _str("GPT_SOVITS_VERSION")
        if v: self.gpt_sovits_version = v
        v = _str("GPT_SOVITS_DEFAULT_CHARACTER")
        if v: self.gpt_sovits_default_character = v
        v = _str("GPT_SOVITS_DEVICE")
        if v: self.gpt_sovits_device = v
        self.gpt_sovits_is_half = _bool("GPT_SOVITS_IS_HALF", self.gpt_sovits_is_half)
        v = _str("GPT_SOVITS_GPT_WEIGHTS")
        if v: self.gpt_sovits_gpt_weights = v
        v = _str("GPT_SOVITS_SOVITS_WEIGHTS")
        if v: self.gpt_sovits_sovits_weights = v

        return self
    gpt_sovits_version: str = Field("v2", env="GPT_SOVITS_VERSION")
    gpt_sovits_default_character: str = Field("陈千语", env="GPT_SOVITS_DEFAULT_CHARACTER")
    gpt_sovits_device: str = Field("cuda:0", env="GPT_SOVITS_DEVICE")
    gpt_sovits_is_half: bool = Field(True, env="GPT_SOVITS_IS_HALF")
    # 训练好的模型权重路径（相对或绝对路径；相对于 GPT-SoVITS 根目录）
    gpt_sovits_gpt_weights: str = Field("", env="GPT_SOVITS_GPT_WEIGHTS")
    gpt_sovits_sovits_weights: str = Field("", env="GPT_SOVITS_SOVITS_WEIGHTS")


class MemoryConfig(BaseModel):
    """记忆系统配置"""
    top_k: int = Field(5, env="MEMORY_TOP_K")
    short_term_db: str = Field("", env="MEMORY_SHORT_TERM_DB")
    long_term_db: str = Field("", env="MEMORY_LONG_TERM_DB")
    user_data_dir: str = Field("user_data", env="MEMORY_USER_DATA_DIR")
    short_term_max: int = Field(2000, env="MEMORY_SHORT_TERM_MAX")
    long_term_max: int = Field(5000, env="MEMORY_LONG_TERM_MAX")
    beta: float = Field(0.5, env="MEMORY_BETA")
    eta: float = Field(0.3, env="MEMORY_ETA")
    weight_threshold: float = Field(0.1, env="MEMORY_WEIGHT_THRESHOLD")
    upgrade_importance_threshold: float = Field(0.7, env="MEMORY_UPGRADE_IMPORTANCE_THRESHOLD")
    upgrade_access_count_threshold: int = Field(5, env="MEMORY_UPGRADE_ACCESS_COUNT_THRESHOLD")
    upgrade_weight_threshold: float = Field(0.5, env="MEMORY_UPGRADE_WEIGHT_THRESHOLD")
    similarity_threshold: float = Field(0.85, env="MEMORY_SIMILARITY_THRESHOLD")
    merge_similarity_threshold: float = Field(0.9, env="MEMORY_MERGE_SIMILARITY_THRESHOLD")
    default_importance: float = Field(0.6, env="MEMORY_DEFAULT_IMPORTANCE")
    context_history_len: int = Field(2, env="MEMORY_CONTEXT_HISTORY_LEN")

    @model_validator(mode='after')
    def _fallback_to_os_environ(self):
        env_val = os.getenv("MEMORY_TOP_K", "")
        if env_val: self.top_k = int(env_val)
        env_val = os.getenv("MEMORY_SHORT_TERM_DB", "")
        if env_val: self.short_term_db = env_val
        env_val = os.getenv("MEMORY_LONG_TERM_DB", "")
        if env_val: self.long_term_db = env_val
        env_val = os.getenv("MEMORY_USER_DATA_DIR", "")
        if env_val: self.user_data_dir = env_val
        env_val = os.getenv("MEMORY_SHORT_TERM_MAX", "")
        if env_val: self.short_term_max = int(env_val)
        env_val = os.getenv("MEMORY_LONG_TERM_MAX", "")
        if env_val: self.long_term_max = int(env_val)
        env_val = os.getenv("MEMORY_BETA", "")
        if env_val: self.beta = float(env_val)
        env_val = os.getenv("MEMORY_ETA", "")
        if env_val: self.eta = float(env_val)
        env_val = os.getenv("MEMORY_WEIGHT_THRESHOLD", "")
        if env_val: self.weight_threshold = float(env_val)
        env_val = os.getenv("MEMORY_UPGRADE_IMPORTANCE_THRESHOLD", "")
        if env_val: self.upgrade_importance_threshold = float(env_val)
        env_val = os.getenv("MEMORY_UPGRADE_ACCESS_COUNT_THRESHOLD", "")
        if env_val: self.upgrade_access_count_threshold = int(env_val)
        env_val = os.getenv("MEMORY_UPGRADE_WEIGHT_THRESHOLD", "")
        if env_val: self.upgrade_weight_threshold = float(env_val)
        env_val = os.getenv("MEMORY_SIMILARITY_THRESHOLD", "")
        if env_val: self.similarity_threshold = float(env_val)
        env_val = os.getenv("MEMORY_MERGE_SIMILARITY_THRESHOLD", "")
        if env_val: self.merge_similarity_threshold = float(env_val)
        env_val = os.getenv("MEMORY_DEFAULT_IMPORTANCE", "")
        if env_val: self.default_importance = float(env_val)
        env_val = os.getenv("MEMORY_CONTEXT_HISTORY_LEN", "")
        if env_val: self.context_history_len = int(env_val)
        return self


class DialogConfig(BaseModel):
    """对话管理配置"""
    max_turns: int = Field(20, env="DIALOG_MAX_TURNS")
    session_ttl_seconds: int = Field(1800, env="DIALOG_SESSION_TTL")
    # 会话轮数超过该值后，触发最早的半段对话的 LLM 滚动摘要（后台任务）
    summary_threshold: int = Field(16, env="DIALOG_SUMMARY_THRESHOLD")
    # 两次滚动摘要之间的最小间隔（秒），避免频繁调用 LLM
    summary_min_interval: int = Field(600, env="DIALOG_SUMMARY_MIN_INTERVAL")
    # 相同消息回复缓存有效期（秒），期间重复提问直接命中缓存
    reply_cache_ttl: int = Field(600, env="REPLY_CACHE_TTL")

    @model_validator(mode='after')
    def _fallback_to_os_environ(self):
        env_val = os.getenv("DIALOG_MAX_TURNS", "")
        if env_val: self.max_turns = int(env_val)
        env_val = os.getenv("DIALOG_SESSION_TTL", "")
        if env_val: self.session_ttl_seconds = int(env_val)
        env_val = os.getenv("DIALOG_SUMMARY_THRESHOLD", "")
        if env_val: self.summary_threshold = int(env_val)
        env_val = os.getenv("DIALOG_SUMMARY_MIN_INTERVAL", "")
        if env_val: self.summary_min_interval = int(env_val)
        env_val = os.getenv("REPLY_CACHE_TTL", "")
        if env_val: self.reply_cache_ttl = int(env_val)
        return self


class ScheduleConfig(BaseModel):
    """定时任务配置"""
    bot_sleep_start: str = Field("22:00", env="BOT_SLEEP_START")
    bot_sleep_end: str = Field("06:00", env="BOT_SLEEP_END")
    memory_maintenance_hour: int = Field(2, env="MEMORY_MAINTENANCE_HOUR")
    memory_maintenance_minute: int = Field(0, env="MEMORY_MAINTENANCE_MINUTE")

    @model_validator(mode='after')
    def _fallback_to_os_environ(self):
        env_val = os.getenv("BOT_SLEEP_START", "")
        if env_val: self.bot_sleep_start = env_val
        env_val = os.getenv("BOT_SLEEP_END", "")
        if env_val: self.bot_sleep_end = env_val
        env_val = os.getenv("MEMORY_MAINTENANCE_HOUR", "")
        if env_val: self.memory_maintenance_hour = int(env_val)
        env_val = os.getenv("MEMORY_MAINTENANCE_MINUTE", "")
        if env_val: self.memory_maintenance_minute = int(env_val)
        return self


class GroupChatConfig(BaseModel):
    """群聊配置"""
    reply_probability: float = Field(0.0, env="GROUP_REPLY_PROBABILITY")
    bot_nickname: str = Field("小玖", env="BOT_NICKNAME")
    reply_cooldown_seconds: float = Field(5.0, env="GROUP_REPLY_COOLDOWN")

    @model_validator(mode='after')
    def _fallback_to_os_environ(self):
        env_val = os.getenv("GROUP_REPLY_PROBABILITY", "")
        if env_val: self.reply_probability = float(env_val)
        env_val = os.getenv("BOT_NICKNAME", "")
        if env_val: self.bot_nickname = env_val
        env_val = os.getenv("GROUP_REPLY_COOLDOWN", "")
        if env_val: self.reply_cooldown_seconds = float(env_val)
        return self


# ──────────────────────────────────────────────
# 主配置
# ──────────────────────────────────────────────

class PluginConfig(BaseSettings):
    """主插件配置，聚合所有子配置组"""
    model_config = SettingsConfigDict(
        env_file=os.path.join(PROJECT_ROOT, ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 子配置组
    llm: LLMConfig = Field(default_factory=LLMConfig)
    asr: ASRConfig = Field(default_factory=ASRConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    dialog: DialogConfig = Field(default_factory=DialogConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    group_chat: GroupChatConfig = Field(default_factory=GroupChatConfig)

    # 多模态（图片处理）开关
    enable_multimodal: bool = Field(True, env="ENABLE_MULTIMODAL")

    # 人设文件
    personality_file: str = Field(
        "src/plugins/nonebot_plugin_update_baisuwen/personality_traits.json",
        env="PERSONALITY_FILE"
    )

    # ── 兼容旧属性（方便已有代码平滑迁移） ──

    @property
    def deepseek_api_key(self) -> str:
        return self.llm.api_key

    @property
    def deepseek_api_base(self) -> str:
        return self.llm.api_base

    @property
    def deepseek_model(self) -> str:
        return self.llm.model

    @property
    def http_timeout(self) -> int:
        return self.llm.timeout

    @property
    def enable_asr(self) -> bool:
        return self.asr.enabled

    @property
    def asr_model_size(self) -> str:
        return self.asr.model_size

    @property
    def asr_device(self) -> str:
        return self.asr.device

    @property
    def asr_language(self) -> str:
        return self.asr.language

    @property
    def enable_tts(self) -> bool:
        return self.tts.enabled

    @property
    def tts_model_path(self) -> str:
        return self.tts.model_path

    @property
    def tts_config_path(self) -> str:
        return self.tts.config_path

    @property
    def tts_always(self) -> bool:
        return self.tts.always

    @property
    def tts_speed(self) -> float:
        return self.tts.speed

    @property
    def tts_noise_scale(self) -> float:
        return self.tts.noise_scale

    @property
    def tts_noise_scale_w(self) -> float:
        return self.tts.noise_scale_w

    @property
    def memory_top_k(self) -> int:
        return self.memory.top_k

    @property
    def bot_sleep_start(self) -> str:
        return self.schedule.bot_sleep_start

    @property
    def bot_sleep_end(self) -> str:
        return self.schedule.bot_sleep_end

    @property
    def memory_maintenance_hour(self) -> int:
        return self.schedule.memory_maintenance_hour

    @property
    def memory_maintenance_minute(self) -> int:
        return self.schedule.memory_maintenance_minute

    @property
    def group_reply_probability(self) -> float:
        return self.group_chat.reply_probability

    @property
    def bot_nickname(self) -> str:
        return self.group_chat.bot_nickname

    # ── 优化配置便捷属性 ──

    @property
    def max_context_tokens(self) -> int:
        return self.llm.max_context_tokens

    @property
    def llm_max_retries(self) -> int:
        return self.llm.max_retries

    @property
    def llm_retry_backoff(self) -> float:
        return self.llm.retry_backoff

    @property
    def stream_reply(self) -> bool:
        return self.llm.stream_reply

    @property
    def memory_extract_min_interval(self) -> int:
        return self.llm.extract_min_interval

    @property
    def memory_extract_model(self) -> str:
        return self.llm.extract_model

    @property
    def dialog_summary_threshold(self) -> int:
        return self.dialog.summary_threshold

    @property
    def dialog_summary_min_interval(self) -> int:
        return self.dialog.summary_min_interval

    @property
    def reply_cache_ttl(self) -> int:
        return self.dialog.reply_cache_ttl

    # ── 工具方法 ──

    def is_sleep_time(self) -> bool:
        """判断当前时间是否在休眠时段内"""
        now = datetime.now().strftime("%H:%M")
        start = self.schedule.bot_sleep_start
        end = self.schedule.bot_sleep_end
        if start <= end:
            return start <= now <= end
        else:  # 跨天，如 22:00 -> 06:00
            return now >= start or now <= end


# 全局配置单例
plugin_config = PluginConfig()
