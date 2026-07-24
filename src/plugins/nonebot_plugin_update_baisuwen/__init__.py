"""
nonebot_plugin_update_baisuwen — 白苏文核心插件

基于 NoneBot2 + DeepSeek AI 的 QQ 伴侣机器人。
多轮对话、记忆系统、语音交互、多模态理解。
"""

__version__ = "1.1.0"

from nonebot import get_driver, logger
from nonebot.plugin import PluginMetadata

from .config import plugin_config
from .event_handler import init_services, message_handler, asr_model, tts_model
from . import scheduler
from . import poke
from . import voice_mode

# ── 插件元数据 ──

__plugin_meta__ = PluginMetadata(
    name="白苏文核心",
    description="基于 NoneBot2 + DeepSeek AI 的 QQ 智能伴侣机器人，支持多轮对话、记忆系统、语音交互、多模态理解",
    usage="直接 @机器人 或发送消息即可对话；/voice 切换语音模式；/admin 管理员命令",
    type="application",
    homepage="https://github.com/baisuwen",
    config=plugin_config.__class__,
    supported_adapters={"~onebot.v11"},
    extra={
        "author": "baisuwen",
        "version": __version__,
    },
)

driver = get_driver()

@driver.on_startup
async def startup():
    from .personality import load_personality
    load_personality()
    init_services()
    logger.info("主插件 nonebot_plugin_update_baisuwen 已启动")


@driver.on_shutdown
async def shutdown():
    from .llm_client import llm_client
    # 停止会话清理
    try:
        from ..nonebot_plugin_dialog import dialog_manager
        dialog_manager.stop_auto_cleanup()
    except Exception:
        pass
    # 关闭 ASR
    if asr_model:
        try:
            asr_model.close()
            logger.info("ASR 模型已关闭")
        except Exception as e:
            logger.error(f"ASR 模型关闭失败: {e}")
    # 关闭 TTS
    if tts_model:
        try:
            tts_model.close()
            logger.info("TTS 模型已关闭")
        except Exception as e:
            logger.error(f"TTS 模型关闭失败: {e}")
    # 关闭 LLM
    if llm_client:
        await llm_client.close()
        logger.info("LLM 客户端已关闭")