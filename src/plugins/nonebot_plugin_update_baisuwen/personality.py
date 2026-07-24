import json
import os
from nonebot import get_driver
from .config import plugin_config, PROJECT_ROOT

_personality_cache = None

def load_personality() -> dict:
    """加载人设 JSON 文件，带缓存"""
    global _personality_cache
    if _personality_cache is not None:
        return _personality_cache

    # 优先使用环境变量中配置的路径，否则使用默认路径
    file_path = plugin_config.personality_file
    if not os.path.isabs(file_path):
        # 相对路径，基于项目根目录
        file_path = os.path.join(PROJECT_ROOT, file_path)

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"人设文件不存在: {file_path}")

    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    _personality_cache = data
    return data


def reload_personality() -> dict:
    """
    热重载人设文件（清除缓存并重新加载）。
    适用于运行时修改人设 JSON 后无需重启。
    """
    global _personality_cache
    _personality_cache = None
    return load_personality()


def get_system_prompt_with_personality(memory_context: str, user_id: str = None) -> str:
    """
    构建包含人设、永不遗忘记忆、检索记忆的 system prompt
    :param memory_context: 检索到的用户相关记忆（已格式化为字符串）
    :param user_id: 当前用户的 QQ 号，用于判断是否为特定主人
    """
    personality = load_personality()
    # 兼容两种 JSON 结构
    if "人物信息" in personality:
        info = personality["人物信息"]
        core_memories = info.get("永不遗忘记忆", [])
        traits = info.get("性格特征", {})
    else:
        info = personality
        core_memories = info.get("core_memories", [])
        traits = info.get("personality_traits", [])

    # 判断是否是特定主人（QQ号 2461292801）
    OWNER_QQ = "2461292801"
    is_owner = (user_id == OWNER_QQ)

    lines = []
    name = info.get('姓名', info.get('name', '白苏文'))
    nickname = info.get('别称', info.get('nickname', '小玖'))
    lines.append(f"你的名字是{name}，别称“{nickname}”。你是一位14岁的狼族兽人少女。")

    if is_owner:
        lines.append("当前与你对话的是你的主人【龙玄月】与【龙星梦】。你对主人绝对忠诚、温柔体贴。")
    else:
        lines.append("当前与你对话的是一位普通用户（朋友或陌生人）。你对普通用户保持礼貌、友善，但不会过度亲密。")

    if '性别' in info:
        lines.append(f"性别：{info['性别']}。")
    if '年龄' in info:
        lines.append(f"年龄：{info['年龄']}岁。")
    if '种族' in info:
        lines.append(f"种族：{info['种族']}。")

    lines.append("你的性格特征：")
    if isinstance(traits, dict):
        for trait, desc in traits.items():
            lines.append(f"- {trait}：{desc}")
    elif isinstance(traits, list):
        for trait_desc in traits:
            lines.append(f"- {trait_desc}")

    # 永不遗忘记忆（对非主人隐藏包含“主人”字样的记忆）
    if core_memories:
        lines.append("\n你永远不会忘记以下事实：")
        for mem in core_memories:
            if not is_owner and "主人" in mem:
                continue
            lines.append(f"- {mem}")

    # 检索到的记忆
    if memory_context and memory_context != "无相关记忆":
        lines.append(f"\n以下是你从与{'主人' if is_owner else '用户'}的对话中记住的一些信息：\n{memory_context}")
    else:
        lines.append(f"\n你目前没有关于{'主人' if is_owner else '这个用户'}的任何记忆，请像初次见面一样友好交流。")

    # 添加说话风格指导（来自人设文件）
    speaking_style = info.get("speaking_style", "说话自然，使用语气词表达情感，不用括号或星号描述动作。")
    typical_phrases = info.get("typical_phrases", [])
    if typical_phrases:
        phrases_str = "、".join(typical_phrases[:5])
        speaking_style += f" 你可以使用这些口头禅：{phrases_str}。"
    response_hint = info.get("response_format_hint", "只输出你说的话，不要使用括号、星号等符号。")

    lines.append(f"\n你的说话风格：{speaking_style}")
    lines.append(f"\n{response_hint}")

    return "\n".join(lines)