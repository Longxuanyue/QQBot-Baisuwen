import json
import os
import re
from nonebot import get_driver, logger
from .config import plugin_config, PROJECT_ROOT

_personality_cache = None

# 情感标签 → 场景块映射（sentiment 插件的 emotion 值 → scene_rules 的键）
# 可在人设 JSON 中用 scene_emotion_map 覆盖
DEFAULT_EMOTION_SCENE_MAP = {
    "happy": ["happy"],
    "excited": ["happy"],
    "sad": ["sad", "serious"],
    "angry": ["angry", "serious"],
    "anxious": ["nervous", "serious"],
    "calm": [],
    "neutral": [],
}


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
        # 人设文件不存在时，从随仓库分发的模板文件自动生成（首次运行引导）
        template_path = os.path.join(
            os.path.dirname(file_path), "personality_traits.template.json"
        )
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                template_data = json.load(f)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(template_data, f, ensure_ascii=False, indent=2)
            logger.warning(f"人设文件不存在，已从模板生成: {file_path}")
            logger.warning("请编辑该文件替换为你自己的角色设定后重启 Bot")
        else:
            raise FileNotFoundError(
                f"人设文件不存在: {file_path}（且未找到模板文件 personality_traits.template.json）"
            )

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


def _resolve(info: dict, *keys, default=None):
    """按顺序尝试多个键名（兼容新旧/中英文键），返回第一个命中的值。"""
    for k in keys:
        if k in info:
            v = info[k]
            if v not in (None, "") and v != 0:
                return v
    return default


def _append_block(lines: list, title: str, items, limit: int = None):
    """以列表形式向 lines 追加一个规则块。items 为 list 或 str。"""
    if not items:
        return
    if isinstance(items, str):
        items = [items]
    lines.append(f"\n{title}")
    for item in items[:limit] if limit else items:
        lines.append(f"- {item}")


def get_system_prompt_with_personality(memory_context: str, user_id: str = None, emotion: str = None) -> str:
    """
    构建包含人设、永不遗忘记忆、检索记忆的 system prompt
    :param memory_context: 检索到的用户相关记忆（已格式化为字符串）
    :param user_id: 当前用户的 QQ 号，用于判断是否为特定主人
    :param emotion: 当前用户消息的情感标签
        （happy/sad/angry/anxious/calm/excited/neutral），用于动态注入
        scene_rules 中对应的场景块；可为 None
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

    # 判断是否为特定主人：必须是 .env 中 SUPERUSERS 配置的超管账号
    # （与项目其他插件的超管判定保持一致，不再使用单独的 OWNER_QQ）
    try:
        superusers = get_driver().config.superusers
        if not isinstance(superusers, (set, list, tuple)):
            superusers = set()
    except Exception:
        superusers = set()
    is_owner = (user_id in superusers)

    lines = []
    name = _resolve(info, "姓名", "name", default="白苏文")
    nickname = _resolve(info, "别称", "nickname", default="小玖")
    gender = _resolve(info, "性别", "gender", default="")
    age = _resolve(info, "年龄", "age", default="")
    race = _resolve(info, "种族", "race", default="")
    birthday = _resolve(info, "生日", "birthday", default="")
    constellation = _resolve(info, "星座", "constellation", default="")

    # ── 1. 基础身份（修复：原先 gender/age/race/birthday/constellation 未正确注入）──
    identity_bits = []
    if name:
        identity_bits.append(f"名字是{name}")
    if nickname:
        identity_bits.append(f"别称“{nickname}”")
    if identity_bits:
        lines.append("你的" + "，".join(identity_bits) + "。")
    attribute_bits = []
    if age:
        attribute_bits.append(f"{age}岁")
    if race:
        attribute_bits.append(race)
    if gender:
        attribute_bits.append(f"性别{gender}")
    if birthday:
        attribute_bits.append(f"生日{birthday}")
    if constellation:
        attribute_bits.append(f"星座{constellation}")
    if attribute_bits:
        lines.append("你是" + "、".join(attribute_bits) + "。")

    # ── 2. 与当前对话者的关系（主人称呼从核心记忆解析，不再硬编码）──
    if is_owner:
        owner_names = []
        for mem in core_memories:
            if "主人" in mem:
                owner_names.extend(re.findall(r"【([^】]+)】", mem))
        # 过滤纯数字（QQ号）与占位文本
        owner_names = [n for n in owner_names if not n.isdigit() and "填写" not in n]
        if owner_names:
            names_str = "、".join(dict.fromkeys(owner_names))
            lines.append(f"当前与你对话的是你的主人【{names_str}】。你对主人绝对忠诚、温柔体贴。")
        else:
            lines.append("当前与你对话的是你的主人。你对主人绝对忠诚、温柔体贴。")
    else:
        lines.append("当前与你对话的是一位普通用户（朋友或陌生人）。你对普通用户保持礼貌、友善，但不会过度亲密。")

    # ── 3. 性格特质（兼容 dict 与 list）──
    lines.append("\n你的性格特征：")
    if isinstance(traits, dict):
        for trait, desc in traits.items():
            lines.append(f"- {trait}：{desc}")
    elif isinstance(traits, list):
        for trait_desc in traits:
            lines.append(f"- {trait_desc}")
    else:
        lines.append("- （未配置性格特征）")

    # ── 4. 核心形象：正反双轨（是什么 / 不是什么）──
    core_identity = info.get("core_identity") or {}
    if isinstance(core_identity, dict):
        _append_block(lines, "你的核心形象：", core_identity.get("is"))
        _append_block(lines, "你不应该是：", core_identity.get("is_not"))

    # ── 5. 场景规则：按当前情绪动态注入（联动 sentiment 插件）──
    scene_rules = info.get("scene_rules") or {}
    scene_emotion_map = info.get("scene_emotion_map") or DEFAULT_EMOTION_SCENE_MAP
    injected_scenes = []
    if isinstance(scene_emotion_map, dict) and emotion and emotion in scene_emotion_map:
        injected_scenes.extend(scene_emotion_map[emotion])
    # 无记忆 → 注入初次见面场景
    if not memory_context or memory_context == "无相关记忆":
        injected_scenes.append("first_meet")
    if isinstance(scene_rules, dict) and injected_scenes:
        scene_items = []
        for key in injected_scenes:
            rule = scene_rules.get(key)
            if rule:
                scene_items.append(f"[{key}] {rule}")
        if scene_items:
            lines.append("\n当前场景下的行为：")
            lines.extend(f"- {item}" for item in scene_items)

    # ── 6. 输出格式控制（回复长度 / 一句一行 / 长回复条件）──
    output_rules = info.get("output_rules") or {}
    if isinstance(output_rules, dict):
        out_items = []
        default_len = output_rules.get("default_length")
        simple_len = output_rules.get("simple_length")
        max_len = output_rules.get("max_length")
        if default_len:
            out_items.append(f"普通回复控制在{default_len}。")
        if simple_len:
            out_items.append(f"简单回复控制在{simple_len}。")
        if max_len:
            out_items.append(f"正常情况下回复不超过{max_len}。")
        if output_rules.get("one_sentence_per_line"):
            out_items.append("一句话一行。")
        if output_rules.get("keep_short"):
            out_items.append("能短答就短答，不写没必要的解释。")
        long_when = output_rules.get("long_reply_allowed_when")
        long_rule = output_rules.get("long_reply_rule")
        if long_when:
            out_items.append(f"仅当用户明确要求（如{'、'.join(long_when[:6])}等）时才允许长回复。")
        if long_rule:
            out_items.append(long_rule)
        _append_block(lines, "回复长度规则：", out_items)

    # ── 7. 标点与表情规则（……/! 的情绪含义、emoji 默认关）──
    punct = info.get("punctuation_rules") or {}
    if isinstance(punct, dict):
        p_items = []
        ellipsis_for = punct.get("ellipsis_for")
        excl_for = punct.get("exclamation_for")
        if ellipsis_for:
            p_items.append(f"在{'、'.join(ellipsis_for[:6])}时使用'……'。")
        if excl_for:
            p_items.append(f"在{'、'.join(excl_for[:6])}时可以使用'!'。")
        if punct.get("question_naturally"):
            p_items.append("疑问句自然使用'？'。")
        if punct.get("avoid_excessive_tilde"):
            p_items.append("不要过度使用'~'。")
        if punct.get("emoji_default_off"):
            p_items.append("默认不使用 emoji。")
        if punct.get("kaomoji_default_off"):
            p_items.append("默认不使用颜文字。")
        _append_block(lines, "标点与表情规则：", p_items)

    # ── 8. 防破功 / 负面清单 / 自然度护栏 / 决策流程 / 记忆策略 ──
    _append_block(lines, "绝对不要做的事：", info.get("anti_meta_rules"))
    _append_block(lines, "避免使用以下表达：", info.get("banned_phrases"))
    _append_block(lines, "自然度要求：", info.get("naturalness_guard"))
    _append_block(lines, "每次回复前的决策流程：", info.get("response_decision"))

    memory_policy = info.get("memory_policy")
    if isinstance(memory_policy, dict):
        _append_block(lines, "记忆使用规则：", memory_policy.get("rules"))

    # ── 9. 说话风格（来自人设文件）──
    speaking_style = info.get("speaking_style", "说话自然，使用语气词表达情感，不用括号或星号描述动作。")
    typical_phrases = info.get("typical_phrases", [])
    if typical_phrases:
        phrases_str = "、".join(typical_phrases[:5])
        speaking_style += f" 你可以使用这些口头禅：{phrases_str}。"
    lines.append(f"\n你的说话风格：{speaking_style}")

    # ── 10. 永不遗忘记忆（对非主人隐藏包含“主人”字样的记忆）──
    visible_memories = [
        mem for mem in core_memories
        if is_owner or "主人" not in mem
    ]
    if visible_memories:
        lines.append("\n你永远不会忘记以下事实：")
        for mem in visible_memories:
            lines.append(f"- {mem}")

    # ── 11. 检索到的记忆 ──
    if memory_context and memory_context != "无相关记忆":
        lines.append(f"\n以下是你从与{'主人' if is_owner else '用户'}的对话中记住的一些信息：\n{memory_context}")
    else:
        lines.append(f"\n你目前没有关于{'主人' if is_owner else '这个用户'}的任何记忆，请像初次见面一样友好交流。")

    # ── 12. 参考示例（对话范本，帮助对齐语气；放在最尾部，预算紧张时优先被截断）──
    examples = info.get("examples")
    if isinstance(examples, list) and examples:
        ex_lines = []
        for ex in examples[:3]:
            if isinstance(ex, dict) and ex.get("user") and ex.get("reply"):
                ex_lines.append(f"用户：{ex['user']}\n你：{ex['reply']}")
        if ex_lines:
            lines.append("\n参考示例：")
            lines.extend(ex_lines)

    # ── 13. 回复格式约束（收尾）──
    response_hint = info.get("response_format_hint", "只输出你说的话，不要使用括号、星号等符号。")
    lines.append(f"\n{response_hint}")

    return "\n".join(lines)
