"""
消息处理核心：编排 ASR → 记忆 → 人设 → LLM → TTS 全流程。

v2 集成:
- 多轮对话管理 (DialogManager)
- 情感分析 (SentimentAnalyzer)
- 用户画像 (UserProfiler)
- 多模态图片理解 (Multimodal)
- 语音模式切换 (VoiceMode)
"""

import random
import re
import time
import asyncio
from contextlib import suppress
from collections import defaultdict, deque
from typing import Any, Optional
from nonebot import on_message, get_driver, logger
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, GroupMessageEvent, MessageSegment
from .config import plugin_config
from .memory_manager import MemoryManager
from .llm_client import llm_client
from .personality import get_system_prompt_with_personality
from .token_budget import trim_messages, truncate_text
from .utils import download_voice_file, silk_to_wav, audio_to_qq_voice
from .group_response import is_group_enabled

# ── 全局模型实例 ──
asr_model = None
tts_model = None

# ── 群聊限流 ──
_last_reply_time: dict = defaultdict(float)

# ── 群聊历史缓存（用于主动互动时的上下文） ──
group_chat_history: dict = defaultdict(lambda: deque(maxlen=50))

# ── 记忆提取节流（每用户最小间隔） ──
_last_memory_extract: dict = defaultdict(float)

# ── 对话滚动摘要节流（按会话） ──
_last_summary_at: dict = {}

# ── 回复缓存 ──
_reply_cache: dict = {}
# 时间敏感消息不命中缓存，避免给出过期答案
_TIME_SENSITIVE_RE = re.compile(r"几点|几点钟|时间|日期|今天|明天|昨天|星期|几号|现在.*[点时]")

# ── 阈值常量 ──
_EXTRACT_MIN_TEXT_LEN = 6   # 记忆提取的最短消息长度
_REPLY_CACHE_MAX = 512      # 回复缓存上限（条）
_STREAM_MIN_DELTA = 2       # 流式刷新最小增量（字符）
_STREAM_FLUSH_CHARS = 24    # 流式刷新阈值（字符）

# 后台任务引用集合（防止任务被 GC 回收）
_bg_tasks: set = set()


def _spawn(coro) -> None:
    """创建后台任务并保留引用"""
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


def init_services():
    """初始化 ASR 和 TTS 模型（在插件启动时调用）"""
    global asr_model, tts_model
    if plugin_config.enable_asr:
        try:
            from ..nonebot_plugin_asr import load_model as load_asr
            asr_model = load_asr(
                model_size=plugin_config.asr_model_size,
                device=plugin_config.asr_device,
                language=plugin_config.asr_language
            )
            logger.info("ASR 模型加载完成")
        except Exception as e:
            logger.error(f"ASR 模型加载失败: {e}")
            asr_model = None

    if plugin_config.enable_tts:
        engine = plugin_config.tts.engine.lower().replace("-", "_")
        try:
            if engine == "gpt_sovits":
                # ── GPT-SoVITS 引擎 ──
                from ..nonebot_plugin_tts.gpt_sovits_engine import GPTSoVITSEngine
                # 注入 sentiment_analyzer 以实现策略3情感路由
                try:
                    from ..nonebot_plugin_sentiment import sentiment_analyzer
                except Exception:
                    sentiment_analyzer = None
                    logger.warning("情感分析模块不可用，GPT-SoVITS 将仅使用关键词+默认路由")
                tts_model = GPTSoVITSEngine(
                    gpt_sovits_config=plugin_config.tts.gpt_sovits_config,
                    default_character=plugin_config.tts.gpt_sovits_default_character,
                    sentiment_analyzer=sentiment_analyzer,
                    version=plugin_config.tts.gpt_sovits_version,
                    device=plugin_config.tts.gpt_sovits_device,
                    is_half=plugin_config.tts.gpt_sovits_is_half,
                    t2s_weights_path=plugin_config.tts.gpt_sovits_gpt_weights,
                    vits_weights_path=plugin_config.tts.gpt_sovits_sovits_weights,
                )
                logger.info(f"GPT-SoVITS 引擎加载完成 (版本={plugin_config.tts.gpt_sovits_version})")
            else:
                # ── VITS 引擎（默认） ──
                from ..nonebot_plugin_tts import load_model as load_tts
                tts_model = load_tts(
                    model_path=plugin_config.tts_model_path,
                    config_path=plugin_config.tts_config_path
                )
                logger.info("VITS 模型加载完成")
        except Exception as e:
            logger.error(f"TTS 模型加载失败 ({engine}): {e}")
            tts_model = None

    # 启动会话自动清理
    try:
        from ..nonebot_plugin_dialog import dialog_manager
        dialog_manager.start_auto_cleanup()
        logger.info("对话管理器已启动")
    except Exception as e:
        logger.debug(f"对话管理器不可用: {e}")


# ── 语音处理 ──

async def process_voice_message(bot: Bot, event: MessageEvent, file_id: str) -> str:
    """处理语音消息，返回识别出的文本。失败时返回空字符串。"""
    if asr_model is None:
        return ""
    try:
        local_path = await download_voice_file(bot, file_id)
        if not local_path:
            return ""
        # 非 wav 格式需要先转换为 wav（silk、amr 等 Whisper 无法直接解码）
        if not local_path.lower().endswith((".wav", ".mp3", ".m4a", ".flac", ".ogg")):
            wav_path = local_path + ".wav"
            # silk 解码/ffmpeg 转换为 CPU 密集阻塞操作，迁移到线程池
            if not await asyncio.to_thread(silk_to_wav, local_path, wav_path):
                logger.warning(f"语音格式转换失败 ({local_path})，将尝试直接用 Whisper 识别")
            else:
                local_path = wav_path
        # Whisper 推理为同步阻塞调用，迁移到线程池，避免阻塞事件循环
        text = await asyncio.to_thread(asr_model.transcribe_file, local_path)
        return text
    except Exception as e:
        logger.error(f"语音识别处理失败: {e}")
        return ""


# ── 记忆生成（后台任务） ──

async def generate_and_store_memory_llm(
    user_id: str, user_msg: str, bot_reply: str, mem_mgr
) -> None:
    """使用 LLM 从对话中生成结构化记忆（后台异步执行）"""
    if not user_msg or not bot_reply:
        return
    if len(user_msg.strip()) < 3 and len(bot_reply.strip()) < 3:
        return

    prompt = f"""你是一个记忆提取助手。根据以下用户和机器人的对话，提取出机器人应该记住的关于用户的**有意义信息**（例如用户的喜好、重要事实、个人特征、说过的重要事情等）。如果对话中没有值得长期记住的信息，只输出"无"。

输出格式要求：
- 如果有信息，输出：记忆内容 | 重要性（0-1之间的小数，表示这条信息的重要程度）
- 如果没有，输出：无

对话：
用户：{user_msg}
机器人：{bot_reply}

记忆："""

    try:
        kwargs = {}
        # 纯文本任务：优先记忆提取专用模型，其次统一纯文本模型（deepseek-v4-flash）
        model = plugin_config.memory_extract_model or plugin_config.llm_text_model
        if model:
            kwargs["model"] = model
        response = await llm_client.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=150,
            **kwargs
        )
        response = response.strip()
        if response == "无" or not response:
            return

        if "|" in response:
            parts = response.rsplit("|", 1)
            content = parts[0].strip()
            try:
                importance = float(parts[1].strip())
                importance = max(0.0, min(1.0, importance))
            except ValueError:
                importance = 0.6
        else:
            content = response
            importance = 0.6

        if len(content) < 3:
            return

        success = mem_mgr.store_memory(content, importance)
        if success:
            logger.info(f"已生成记忆: {content} (重要性={importance})")
        else:
            logger.debug(f"记忆存储失败（可能重复或无效）: {content}")
    except Exception as e:
        logger.error(f"LLM 生成记忆失败: {e}")


# ── 记忆提取节流 ──

def _should_extract_memory(
    user_id: str, msg_text: str, *, is_group: bool, event: MessageEvent
) -> bool:
    """记忆提取节流：群聊非@不提取、短消息不提取、每用户最小间隔"""
    if is_group and not event.to_me:
        return False
    if len(msg_text.strip()) < _EXTRACT_MIN_TEXT_LEN:
        return False
    now = time.time()
    last = _last_memory_extract.get(user_id, 0.0)
    if now - last < plugin_config.memory_extract_min_interval:
        return False
    _last_memory_extract[user_id] = now
    return True


# ── 对话滚动摘要 ──

def _maybe_summarize_dialog(
    user_id: str, group_id: Any = None, dialog_manager: Any = None
) -> None:
    """会话轮数超阈值时，后台压缩最早的一半消息为滚动摘要"""
    try:
        turns = len(dialog_manager.get_context(user_id, group_id, last_n=1000)) // 2
        if turns < plugin_config.dialog_summary_threshold:
            return
        key = (user_id, group_id or "private")
        now = time.time()
        last = _last_summary_at.get(key, 0.0)
        if now - last < plugin_config.dialog_summary_min_interval:
            return
        _last_summary_at[key] = now
        context = dialog_manager.get_context(user_id, group_id, last_n=1000)
        oldest = context[: len(context) // 2]
        if not oldest:
            return
        _spawn(_summarize_and_compact(user_id, group_id, oldest, dialog_manager))
    except Exception as e:
        logger.debug(f"滚动摘要调度失败: {e}")


async def _summarize_and_compact(
    user_id: str,
    group_id: Any = None,
    oldest_msgs: Optional[list[dict]] = None,
    dialog_manager: Any = None,
) -> None:
    """调用 LLM 压缩最早的消息，写入会话摘要并移除原文"""
    if not oldest_msgs:
        return
    try:
        lines = "\n".join(
            (
                f"用户{m.get('user_id', '?')}: {m['content'][:200]}"
                if m["role"] == "user"
                else f"你: {m['content'][:200]}"
            )
            for m in oldest_msgs
        )
        prompt = (
            f"请用2-3句话总结以下对话的要点（主题、关键信息、双方的约定与喜好）。\n"
            f"只输出总结内容：\n{lines}"
        )
        kwargs = {}
        if plugin_config.llm_text_model:
            kwargs["model"] = plugin_config.llm_text_model
        summary = await llm_client.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=120,
            **kwargs,
        )
        summary = summary.strip()
        if summary:
            dialog_manager.set_summary(user_id, summary, group_id)
            dialog_manager.pop_oldest(user_id, len(oldest_msgs), group_id)
            logger.info(
                f"对话滚动摘要完成 | user={user_id} | 压缩 {len(oldest_msgs)} 条消息"
            )
    except Exception as e:
        logger.debug(f"对话滚动摘要失败: {e}")


# ── 回复缓存 ──

def _cache_key(user_id: str, group_id: Any, msg_text: str) -> str:
    return f"{user_id}|{group_id or 'private'}|{msg_text}"


def _get_cached_reply(user_id: str, group_id: Any, msg_text: str) -> str:
    """获取缓存的回复；时间敏感消息不命中"""
    if plugin_config.reply_cache_ttl <= 0:
        return ""
    if _TIME_SENSITIVE_RE.search(msg_text):
        return ""
    key = _cache_key(user_id, group_id, msg_text)
    entry = _reply_cache.get(key)
    if not entry:
        return ""
    ts, reply = entry
    if time.time() - ts > plugin_config.reply_cache_ttl:
        _reply_cache.pop(key, None)
        return ""
    return reply


def _set_cached_reply(
    user_id: str, group_id: Any, msg_text: str, reply: str
) -> None:
    """写入回复缓存（带上限，防止无限增长）"""
    if plugin_config.reply_cache_ttl <= 0 or not reply:
        return
    if len(_reply_cache) >= _REPLY_CACHE_MAX:
        keys = list(_reply_cache.keys())
        for k in keys[: len(keys) // 2]:
            _reply_cache.pop(k, None)
    _reply_cache[_cache_key(user_id, group_id, msg_text)] = (time.time(), reply)


# ── 流式回复 ──

async def _stream_reply(
    bot: Bot, event: MessageEvent, messages: list[dict]
) -> str:
    """流式回复：边生成边发送，新消息替换上一条（OneBot delete_msg）。"""
    prev_id = None
    buffer = ""
    last_sent = ""
    try:
        async for delta in llm_client.chat_completion_stream(messages):
            buffer += delta
            if len(buffer) - len(last_sent) < _STREAM_MIN_DELTA:
                continue
            # 每 ~24 字符或遇到句末标点刷新一次
            if len(buffer) - len(last_sent) >= _STREAM_FLUSH_CHARS or any(
                ch in buffer[len(last_sent):] for ch in "。！？!?\n"
            ):
                sent = await bot.send(event, MessageSegment.text(buffer))
                mid = sent if isinstance(sent, (str, int)) else getattr(
                    sent, "message_id", None
                )
                if prev_id is not None:
                    with suppress(Exception):
                        await bot.delete_msg(message_id=prev_id)
                prev_id = mid
                last_sent = buffer
        if buffer and last_sent != buffer:
            sent = await bot.send(event, MessageSegment.text(buffer))
            mid = sent if isinstance(sent, (str, int)) else getattr(
                sent, "message_id", None
            )
            if prev_id is not None and mid != prev_id:
                with suppress(Exception):
                    await bot.delete_msg(message_id=prev_id)
    except Exception as e:
        logger.error(f"流式回复失败: {e}")
        raise
    return buffer


# ── 辅助函数 ──

def _should_use_voice(
    is_group: bool,
    user_id: str,
    group_id: Optional[int] = None,
    *,
    incoming_voice: bool = False,
) -> bool:
    """判断是否应该使用语音回复

    :param is_group: 是否是群聊消息
    :param user_id: 用户 QQ 号
    :param group_id: 群号（仅群聊时使用）
    :param incoming_voice: 用户发送的消息是否为语音（用于 auto 模式判断）

    优先级（从高到低）：
    1. TTS 不可用（ENABLE_TTS=false 或模型加载失败）→ 永不语音
    2. TTS_ALWAYS=true → 全局强制语音，覆盖所有会话级设置
    3. 群聊 → 按该群的语音模式（/群语音，与私聊互相隔离）：
       - always: 总是语音回复
       - text:   总是文字回复
       - auto:   语音进→语音出，文字进→文字出
    4. 私聊 → 按用户设置的语音模式（/voicemode）：
       - always: 总是语音回复
       - text:   总是文字回复
       - auto:   语音进→语音出，文字进→文字出
    """
    if not plugin_config.enable_tts or tts_model is None:
        return False

    # 全局强制语音（管理员级总开关，覆盖群/用户的细粒度设置）
    if plugin_config.tts_always:
        return True

    # 群聊：读取该群的语音模式（与私聊互相隔离）
    if is_group:
        try:
            from .group_voice_mode import get_group_voice_mode
            mode = get_group_voice_mode(group_id)
        except Exception:
            mode = "auto"
        if mode == "always":
            return True
        elif mode == "text":
            return False
        else:  # auto: 语音进语音出，文字进文字出
            return incoming_voice

    # 私聊：读取用户语音偏好
    try:
        from .voice_mode import get_voice_mode
        mode = get_voice_mode(user_id)
    except Exception:
        mode = "auto"

    if mode == "always":
        return True
    elif mode == "text":
        return False
    else:  # auto: 语音进语音出，文字进文字出
        return incoming_voice


async def _build_system_prompt_with_context(
    user_id: str, msg_text: str, is_group: bool,
    group_id: Optional[int] = None
) -> str:
    """构建包含人设、记忆、画像、情感、对话上下文的完整 system prompt"""

    # 1. 记忆检索（上下文感知：拼最近对话解决指代，如"那个活动"）
    mem_mgr = MemoryManager.get_manager(user_id)
    history = []
    try:
        from ..nonebot_plugin_dialog import dialog_manager
        hctx = dialog_manager.get_context(user_id, group_id, last_n=2)
        history = [m["content"] for m in hctx if m.get("role") == "user"]
    except Exception:
        pass
    memories = mem_mgr.retrieve_memories(
        msg_text, top_k=plugin_config.memory_top_k, update_access=True,
        conversation_history=history[-2:] or None,
    )
    memory_context = (
        "\n".join([f"- {m['content']}" for m in memories])
        if memories else "无相关记忆"
    )
    # 记忆上下文体积裁剪，限制注入 token
    if memory_context != "无相关记忆":
        memory_context = truncate_text(memory_context, 400)

    # 2. 用户画像（如果有）
    profile_text = ""
    try:
        from ..nonebot_plugin_profile import profiler
        profile_text = profiler.get_profile_summary(user_id)
        if profile_text:
            profile_text = truncate_text(profile_text, 200)
    except Exception:
        pass

    # 3. 情感分析（如果有）：情感提示文本 + 情感标签（供人设场景规则动态注入）
    emotion_hint = ""
    emotion = None
    try:
        from ..nonebot_plugin_sentiment import sentiment_analyzer
        emotion_hint = sentiment_analyzer.get_emotional_context(msg_text)
        _emotion_result = sentiment_analyzer.analyze(msg_text)
        if _emotion_result.get("confidence", 0) >= 0.5:
            emotion = _emotion_result.get("emotion")
    except Exception:
        pass

    # 4. 当前话题（轻量注入；完整历史由 messages 数组承载，避免重复计费）
    topic_hint = ""
    try:
        from ..nonebot_plugin_dialog import dialog_manager
        topic_hint = dialog_manager.get_topic(user_id, group_id)
    except Exception:
        pass

    # 5. 人设 + 记忆 → system prompt（情感标签用于动态注入场景规则）
    system_prompt = get_system_prompt_with_personality(memory_context, user_id, emotion=emotion)

    # 6. 追加附加信息
    additions = []
    if profile_text:
        additions.append(f"关于该用户的信息：\n{profile_text}")
    if emotion_hint:
        additions.append(emotion_hint)
    if topic_hint:
        additions.append(f"当前话题：{topic_hint}")

    # 5.5 群聊：注入群上下文块（群记忆/风格卡/话题/昵称，预算受限）
    if is_group and group_id is not None:
        try:
            from ..nonebot_plugin_groupmind import groupmind
            group_ctx = groupmind.build_group_context(group_id, msg_text)
            if group_ctx:
                additions.append(group_ctx)
        except Exception:
            pass

    if additions:
        system_prompt += "\n\n" + "\n\n".join(additions)

    return system_prompt


async def _handle_image_segments(bot: Bot, event: MessageEvent) -> str:
    """处理消息中的图片段，返回图片描述文本"""
    try:
        from ..nonebot_plugin_multimodal import handle_image_message
        desc = await handle_image_message(
            bot, event, llm_client,
            model=plugin_config.llm_vision_model or None,
            max_tokens=plugin_config.llm_vision_max_tokens,
        )
        return desc or ""
    except Exception as e:
        logger.warning(f"图片处理异常: {e!r}")
        return ""


# ── 主消息处理 ──

message_handler = on_message(priority=10, block=False)


@message_handler.handle()
async def handle_message(bot: Bot, event: MessageEvent):
    user_id = str(event.user_id)
    msg_text = event.get_plaintext().strip()
    is_group = isinstance(event, GroupMessageEvent)

    logger.info(
        f"收到消息 | user={user_id} | "
        f"type={'群聊' if is_group else '私聊'} | "
        f"text={msg_text[:80] if msg_text else '(空)'}"
    )

    # 休眠时段不响应
    if plugin_config.is_sleep_time():
        logger.info(
            f"休眠时段 ({plugin_config.bot_sleep_start}–{plugin_config.bot_sleep_end})，"
            f"忽略消息 from {user_id}"
        )
        return

    # 按群响应开关：关闭响应的群完全不响应（含 @、昵称呼唤与主动搭话）
    if is_group and not is_group_enabled(event.group_id):
        logger.info(
            f"群 {event.group_id} 已关闭响应，忽略消息 from {user_id}"
        )
        return
    was_voice = False  # 追踪入站消息是否为语音

    # 如果消息是命令（以 command_start 前缀开头），跳过聊天处理
    # 避免与指令类插件（如 skland、admin 等）产生冲突
    command_start = get_driver().config.command_start
    if msg_text and any(
        prefix and msg_text.startswith(prefix) for prefix in command_start
    ):
        logger.debug(f"消息是命令，跳过聊天处理: {msg_text[:50]}")
        return

    # 语音识别处理：检测 record 类型的消息段
    has_record = any(seg.type == "record" for seg in event.message)
    if has_record and plugin_config.enable_asr and asr_model:
        for seg in event.message:
            if seg.type == "record":
                # 优先 url（可直接 HTTP 下载），其次 path/file（本地/协议引用）
                file_id = (
                    seg.data.get("url")
                    or seg.data.get("path")
                    or seg.data.get("file")
                    or seg.data.get("file_id")
                )
                if file_id:
                    voice_text = await process_voice_message(bot, event, file_id)
                    if voice_text:
                        logger.info(f"ASR 识别结果: {voice_text}")
                        was_voice = True
                        # 语音内容优先于文字（用户发的就是语音，ASR结果是其主要内容）
                        msg_text = voice_text if not msg_text else msg_text
                break

    # ── 是否会产生回复：提前判定（与图片内容无关）。放在识图之前，
    #    避免为「不回复的带图消息」白白调用一次视觉模型 ──
    will_reply = True
    group_id = event.group_id if is_group else None
    if is_group:
        if event.to_me:
            pass  # @ 必定回复
        else:
            now = time.time()
            last_time = _last_reply_time.get(event.group_id, 0)
            if now - last_time < plugin_config.group_chat.reply_cooldown_seconds:
                will_reply = False
            else:
                # 自适应回复概率：基础概率 × 群氛围分（需开启 GROUP_ADAPTIVE_PROBABILITY）
                prob = plugin_config.group_reply_probability
                if prob > 0:
                    try:
                        from ..nonebot_plugin_groupmind import groupmind
                        prob *= groupmind.get_adaptive_factor(event.group_id)
                    except Exception:
                        pass
                if random.random() >= prob:
                    will_reply = False
                else:
                    # 通过概率门限，记录本次回复时间，供后续冷却计算使用
                    _last_reply_time[event.group_id] = now

    # 图片处理（多模态，可通过 ENABLE_MULTIMODAL 关闭；仅当确定会回复时才识图）
    if will_reply and plugin_config.enable_multimodal:
        # image 段（正常图片消息）或 file 段（以文件形式发送的图片）
        has_image = any(
            seg.type in ("image", "file") for seg in event.message
        )
        if has_image:
            image_desc = await _handle_image_segments(bot, event)
            if image_desc:
                msg_text = f"{msg_text}\n{image_desc}" if msg_text else image_desc

    if not msg_text:
        logger.info("消息文本为空，跳过处理")
        return

    # 群聊：记录消息历史 + 群聊学习采集（对每条群消息都执行，与是否回复无关）
    if is_group:
        group_chat_history[event.group_id].append((
            event.user_id, msg_text, 0
        ))

        # ── 群聊学习采集（内存缓冲 + 异步批量写盘，不阻塞主链路） ──
        try:
            from ..nonebot_plugin_groupmind import groupmind
            await groupmind.ingest(bot, event, msg_text)
        except Exception as e:
            logger.debug(f"群聊学习采集失败: {e}")

        if not will_reply:
            return

    # 确认回复后才初始化记忆管理器（惰性建库，避免为不回复的群消息创建空库）
    mem_mgr = MemoryManager.get_manager(user_id)

    # ── 更新对话管理器 ──
    try:
        from ..nonebot_plugin_dialog import dialog_manager
        dialog_manager.add_turn(
            user_id, "user", msg_text, group_id,
            speaker_id=user_id if is_group else None,
        )
    except Exception:
        pass

    # ── 构建 system prompt ──
    system_prompt = await _build_system_prompt_with_context(
        user_id, msg_text, is_group, group_id
    )

    # ── 构建 messages ──
    messages = [{"role": "system", "content": system_prompt}]

    # 注入滚动摘要（更早对话的压缩纪要，替代被压缩掉的原始消息）
    try:
        from ..nonebot_plugin_dialog import dialog_manager
        summary = dialog_manager.get_summary(user_id, group_id)
        if summary:
            messages.insert(
                1,
                {"role": "system", "content": f"对话纪要（更早的对话）：\n{summary}"},
            )
    except Exception:
        pass

    # 尝试注入多轮对话历史（作为 assistant/user 交替消息）
    try:
        from ..nonebot_plugin_dialog import dialog_manager
        context = dialog_manager.get_context(user_id, group_id, last_n=6)
        if context and not (is_group and not event.to_me):
            if is_group:
                # 群聊：标注每条用户消息的说话人（昵称优先），避免张冠李戴
                try:
                    from ..nonebot_plugin_groupmind import groupmind
                except Exception:
                    groupmind = None
                labeled = []
                for m in context:
                    if (
                        m.get("role") == "user"
                        and m.get("user_id")
                        and groupmind is not None
                    ):
                        label = groupmind.format_speaker(
                            group_id, m["user_id"]
                        )
                        labeled.append({
                            **m,
                            "content": f"用户{label}：{m['content']}",
                        })
                    else:
                        labeled.append(m)
                messages.extend(labeled)
            else:
                messages.extend(context)
    except Exception:
        pass

    if not any(m.get("role") == "user" and m.get("content") == msg_text
               for m in messages):
        # 构建用户消息
        if is_group and not event.to_me:
            # 主动互动：附上群聊上下文（唯一的历史注入点，避免重复计费）
            history_list = list(group_chat_history.get(event.group_id, []))
            recent = history_list[-5:]
            history_text = ""
            if recent:
                history_lines = [
                    f"用户{uid}: {cont}" for uid, cont, _ in recent
                ]
                history_text = (
                    "以下是群聊中最近的对话记录（按时间顺序）：\n"
                    + "\n".join(history_lines) + "\n\n"
                )
            user_content = (
                f"{history_text}现在用户{event.user_id}说：{msg_text}\n"
                "请根据整个对话内容，以你的角色身份自然地回复。"
            )
            messages.append({"role": "user", "content": user_content})
        else:
            messages.append({"role": "user", "content": msg_text})

    # ── Token 预算裁剪：超出预算时优先丢弃最旧历史 ──
    messages = trim_messages(messages, plugin_config.max_context_tokens)

    # 语音模式判定（用于流式/语音发送决策）
    use_voice = _should_use_voice(
        is_group, user_id, group_id, incoming_voice=was_voice
    )

    # ── 回复缓存：相同消息在 TTL 内直接复用，省一次 LLM 调用 ──
    cached_reply = _get_cached_reply(user_id, group_id, msg_text)
    if cached_reply:
        logger.info(f"回复缓存命中 | user={user_id}")
        reply = cached_reply
    else:
        # ── 调用 LLM ──
        logger.info(
            f"调用 LLM | model={llm_client.model} | messages={len(messages)} 条"
        )
        try:
            if plugin_config.stream_reply and not use_voice:
                reply = await _stream_reply(bot, event, messages)
            else:
                reply = await llm_client.chat_completion(messages)
            logger.info(f"LLM 回复 | len={len(reply)} | text={reply[:80]}...")
            _set_cached_reply(user_id, group_id, msg_text, reply)
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            reply = "呜呜呜，小白的脑袋好像过载了……快去联系龙小月主人┭┮﹏┭┮"
    try:
        from ..nonebot_plugin_dialog import dialog_manager
        dialog_manager.add_turn(user_id, "assistant", reply, group_id)
        # 会话过长时触发后台滚动摘要
        _maybe_summarize_dialog(user_id, group_id, dialog_manager)
    except Exception:
        pass

    # ── 后台记忆生成（节流 + 群聊非@不提取） ──
    if _should_extract_memory(
        user_id, msg_text, is_group=is_group, event=event
    ):
        asyncio.create_task(
            generate_and_store_memory_llm(user_id, msg_text, reply, mem_mgr)
        )

    # ── 发送回复 ──
    logger.info(f"发送回复 | voice={use_voice} | len={len(reply)}")

    if use_voice:
        if tts_model is None:
            await bot.send(event, reply)
            return
        try:
            # TTS 合成为 CPU/GPU 密集阻塞操作，迁移到线程池
            sr, audio = await asyncio.to_thread(
                tts_model.synthesize,
                reply,
                speed=plugin_config.tts_speed,
                noise_scale=plugin_config.tts_noise_scale,
                noise_scale_w=plugin_config.tts_noise_scale_w
            )
            voice_seg = audio_to_qq_voice(audio, sr)
            await bot.send(event, voice_seg)
        except Exception as e:
            logger.error(f"TTS 合成失败: {e}")
            await bot.send(event, reply)
    else:
        await bot.send(event, reply)

    # ── 群聊学习：记录 bot 回复（开启氛围分接话窗口） ──
    if is_group:
        try:
            from ..nonebot_plugin_groupmind import groupmind
            groupmind.note_bot_reply(event.group_id)
        except Exception:
            pass
