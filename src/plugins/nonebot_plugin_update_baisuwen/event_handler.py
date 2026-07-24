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
import asyncio
from collections import defaultdict, deque
from nonebot import on_message, get_driver, logger
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, GroupMessageEvent, MessageSegment
from .config import plugin_config
from .memory_manager import MemoryManager
from .llm_client import llm_client
from .personality import get_system_prompt_with_personality
from .utils import download_voice_file, silk_to_wav, audio_to_qq_voice

# ── 全局模型实例 ──
asr_model = None
tts_model = None

# ── 群聊限流 ──
_last_reply_time: dict = defaultdict(float)

# ── 群聊历史缓存（用于主动互动时的上下文） ──
group_chat_history: dict = defaultdict(lambda: deque(maxlen=50))


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
    try:
        local_path = await download_voice_file(bot, file_id)
        if not local_path:
            return ""
        # 非 wav 格式需要先转换为 wav（silk、amr 等 Whisper 无法直接解码）
        if not local_path.lower().endswith((".wav", ".mp3", ".m4a", ".flac", ".ogg")):
            wav_path = local_path + ".wav"
            if not silk_to_wav(local_path, wav_path):
                logger.warning(f"语音格式转换失败 ({local_path})，将尝试直接用 Whisper 识别")
            else:
                local_path = wav_path
        text = asr_model.transcribe_file(local_path)
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
        response = await llm_client.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=150
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


# ── 辅助函数 ──

def _should_use_voice(is_group: bool, user_id: str, *, incoming_voice: bool = False) -> bool:
    """判断是否应该使用语音回复

    :param is_group: 是否是群聊消息
    :param user_id: 用户 QQ 号
    :param incoming_voice: 用户发送的消息是否为语音（用于 auto 模式判断）

    规则：
    - 群聊始终返回 False（只发文字）
    - 私聊根据用户设置的语音模式决定：
      - always: 总是语音回复
      - text:   总是文字回复
      - auto:   语音进→语音出，文字进→文字出
    """
    if not plugin_config.enable_tts or tts_model is None:
        return False

    # 群聊始终文字回复
    if is_group:
        return False

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
    group_id: int = None
) -> str:
    """构建包含人设、记忆、画像、情感、对话上下文的完整 system prompt"""

    # 1. 记忆检索
    mem_mgr = MemoryManager.get_manager(user_id)
    memories = mem_mgr.retrieve_memories(
        msg_text, top_k=plugin_config.memory_top_k, update_access=True
    )
    memory_context = (
        "\n".join([f"- {m['content']}" for m in memories])
        if memories else "无相关记忆"
    )

    # 2. 用户画像（如果有）
    profile_text = ""
    try:
        from ..nonebot_plugin_profile import profiler
        profile_text = profiler.get_profile_summary(user_id)
    except Exception:
        pass

    # 3. 情感分析（如果有）
    emotion_hint = ""
    try:
        from ..nonebot_plugin_sentiment import sentiment_analyzer
        emotion_hint = sentiment_analyzer.get_emotional_context(msg_text)
    except Exception:
        pass

    # 4. 对话历史上下文（如果有多轮对话管理器）
    dialog_context = ""
    try:
        from ..nonebot_plugin_dialog import dialog_manager
        dialog_context = dialog_manager.get_context_text(
            user_id, group_id, last_n=4
        )
    except Exception:
        pass

    # 5. 人设 + 记忆 → system prompt
    system_prompt = get_system_prompt_with_personality(memory_context, user_id)

    # 6. 追加附加信息
    additions = []
    if profile_text:
        additions.append(f"关于该用户的信息：\n{profile_text}")
    if emotion_hint:
        additions.append(emotion_hint)
    if dialog_context:
        additions.append(f"最近的对话历史：\n{dialog_context}")

    if additions:
        system_prompt += "\n\n" + "\n\n".join(additions)

    return system_prompt


async def _handle_image_segments(bot: Bot, event: MessageEvent) -> str:
    """处理消息中的图片段，返回图片描述文本"""
    try:
        from ..nonebot_plugin_multimodal import handle_image_message
        desc = await handle_image_message(bot, event, llm_client)
        return desc or ""
    except Exception:
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

    # 图片处理（多模态，可通过 ENABLE_MULTIMODAL 关闭）
    if plugin_config.enable_multimodal:
        image_desc = ""
        has_image = any(seg.type == "image" for seg in event.message)
        if has_image:
            image_desc = await _handle_image_segments(bot, event)
            if image_desc:
                msg_text = f"{msg_text}\n{image_desc}" if msg_text else image_desc

    if not msg_text:
        logger.info("消息文本为空，跳过处理")
        return

    # 获取用户记忆管理器
    mem_mgr = MemoryManager.get_manager(user_id)

    # 群聊限流逻辑
    group_id = event.group_id if is_group else None

    if is_group:
        # 记录群聊消息
        group_chat_history[event.group_id].append((
            event.user_id, msg_text, 0
        ))

        if event.to_me:
            pass  # 必定回复
        else:
            import time as _time
            now = _time.time()
            last_time = _last_reply_time.get(event.group_id, 0)
            if now - last_time < plugin_config.group_chat.reply_cooldown_seconds:
                return
            if random.random() >= plugin_config.group_reply_probability:
                return
            _last_reply_time[event.group_id] = now

    # ── 更新对话管理器 ──
    try:
        from ..nonebot_plugin_dialog import dialog_manager
        dialog_manager.add_turn(user_id, "user", msg_text, group_id)
    except Exception:
        pass

    # ── 构建 system prompt ──
    system_prompt = await _build_system_prompt_with_context(
        user_id, msg_text, is_group, group_id
    )

    # ── 构建 messages ──
    messages = [{"role": "system", "content": system_prompt}]

    # 尝试注入多轮对话历史（作为 assistant/user 交替消息）
    try:
        from ..nonebot_plugin_dialog import dialog_manager
        context = dialog_manager.get_context(user_id, group_id, last_n=6)
        if context and not (is_group and not event.to_me):
            # 私聊或被@时注入完整对话历史
            messages.extend(context)
    except Exception:
        pass

    if not any(m.get("role") == "user" and m.get("content") == msg_text
               for m in messages):
        # 构建用户消息
        if is_group and not event.to_me:
            # 主动互动：附上群聊上下文
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

    # ── 调用 LLM ──
    logger.info(f"调用 LLM | model={llm_client.model} | messages={len(messages)} 条")
    try:
        reply = await llm_client.chat_completion(messages)
        logger.info(f"LLM 回复 | len={len(reply)} | text={reply[:80]}...")
    except Exception as e:
        logger.error(f"LLM 调用失败: {e}")
        reply = "呜呜呜，小白的脑袋好像过载了……快去联系龙小月主人┭┮﹏┭┮"
    try:
        from ..nonebot_plugin_dialog import dialog_manager
        dialog_manager.add_turn(user_id, "assistant", reply, group_id)
    except Exception:
        pass

    # ── 后台记忆生成 ──
    asyncio.create_task(
        generate_and_store_memory_llm(user_id, msg_text, reply, mem_mgr)
    )

    # ── 发送回复 ──
    use_voice = _should_use_voice(is_group, user_id, incoming_voice=was_voice)
    logger.info(f"发送回复 | voice={use_voice} | len={len(reply)}")

    if use_voice:
        try:
            sr, audio = tts_model.synthesize(
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
