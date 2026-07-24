from typing import List, Dict, Any, Tuple, Optional
from pathlib import Path
from .data_manager import find_image_path


def format_entry_detail(entry: Dict[str, Any]) -> Tuple[str, Optional[Path]]:
    """格式化单个条目的详细信息，返回文本和图片路径"""
    lines = []
    name = entry.get("name", "未知")
    eid = entry.get("id", "")
    category = entry.get("category", "")
    sub_tags = entry.get("subTags", [])
    quantity = entry.get("quantity")
    duration = entry.get("durationRounds")
    defeat_reward = entry.get("defeatReward")
    perfect_reward = entry.get("perfectReward")
    special = entry.get("specialMechanism", "暂未录入")

    lines.append(f"名称：{name}")
    lines.append(f"编号：{eid}")
    lines.append(f"类别：{category}")
    if sub_tags:
        lines.append(f"标签：{'、'.join(sub_tags)}")
    if quantity is not None:
        lines.append(f"数量：{quantity}")
    if duration is not None:
        lines.append(f"持续场次：{duration}")
    if defeat_reward is not None:
        lines.append(f"击败奖励资金：{defeat_reward}")
    if perfect_reward is not None:
        lines.append(f"完美作战奖励：{perfect_reward}")
    lines.append(f"特殊机制：{special}")

    text = "\n".join(lines)
    img_path = find_image_path(name, eid)
    return text, img_path


def build_name_list_message(entries: List[Dict[str, Any]], keyword_hint: str = "") -> str:
    """构建多结果列表消息（用于重名或标签查询结果）"""
    if not entries:
        return "对不起，未能查询到对应信息，请您重新输入"

    if keyword_hint:
        lines = [f"以下敌人包含了【{keyword_hint}】信息，请您确认要查询的是哪一位？"]
    else:
        lines = ["查询到以下敌人信息，请确认："]

    for entry in entries:
        name = entry.get("name", "")
        eid = entry.get("id", "")
        tags = "】【".join(entry.get("subTags", []))
        lines.append(f"【{name}】【{eid}】【{tags}】")
    return "\n".join(lines)