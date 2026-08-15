"""
群聊学习 LLM 批量任务（每日低频，成本可控）：
- 群记忆提取：把当日群消息提炼为群级事实，存入群记忆库
- 群风格卡：把最近消息与统计总结为结构化"群设"，供上下文注入
"""

import json
import os
import time
from typing import Optional

from nonebot import logger

from ..nonebot_plugin_memory.generation import store_memory
from ..nonebot_plugin_memory.retrieval import retrieve_memories

from . import storage
from .config import (
    GROUP_MEMORY_TOP_K, GROUP_STYLE_MODEL,
)

# 单群消息量的安全上限（超出截断，防超长 prompt）
_MAX_EXTRACT_MSGS = 200
_MAX_STYLE_MSGS = 500


def _pick_model(update_baisuwen_config) -> str:
    """模型选择：群学习专用模型 > 记忆提取模型 > 主对话模型"""
    if GROUP_STYLE_MODEL:
        return GROUP_STYLE_MODEL
    try:
        if update_baisuwen_config and update_baisuwen_config.memory_extract_model:
            return update_baisuwen_config.memory_extract_model
    except Exception:
        pass
    return ""


async def extract_group_memories(
    group_id, llm_client, update_baisuwen_config=None,
) -> int:
    """批量提取群记忆：当日消息 → LLM 提炼 3~5 条 → 存群库，返回新增条数"""
    db_path = storage.group_db_path(group_id)
    if not os.path.exists(db_path):
        return 0
    since = time.time() - 24 * 3600
    msgs = storage.get_recent_messages(db_path, _MAX_EXTRACT_MSGS, since_ts=since)
    if len(msgs) < 3:
        return 0
    lines = []
    for m in msgs[-_MAX_EXTRACT_MSGS:]:
        content = m["content"].replace("\n", " ")[:120]
        lines.append(f"用户{m['user_id']}: {content}")
    prompt = (
        "以下是某个QQ群今天（24小时内）的部分聊天记录。请提炼出值得机器人长期记住的"
        "群级信息（如：群成员昵称与对应关系、群内固定活动/约定、反复出现的话题、"
        "群内常用梗的准确含义）。只输出事实，不要输出建议或评价。\n"
        "要求：\n"
        "1. 最多输出5条，最少0条\n"
        "2. 每条格式：事实内容 | 重要性(0-1小数)\n"
        "3. 没有值得记住的信息时只输出：无\n"
        "聊天记录：\n" + chr(10).join(lines)
    )
    try:
        kwargs = {}
        model = _pick_model(update_baisuwen_config)
        if model:
            kwargs["model"] = model
        response = await llm_client.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=300,
            **kwargs,
        )
    except Exception as e:
        logger.debug(f"群记忆提取失败 [{group_id}]: {e}")
        return 0

    stored = 0
    for content, imp in _parse_extract_response(response):
        if store_memory(content, imp, db_path=db_path):
            stored += 1
    if stored:
        logger.info(f"群记忆提取 [{group_id}]: 新增 {stored} 条")
    return stored


def _parse_extract_response(response: str) -> list:
    """解析群记忆提取响应：'内容 | 重要性' 行 → [(内容, 重要性)]"""
    result = []
    for raw_line in response.strip().splitlines():
        line = raw_line.strip().lstrip("- ").strip()
        if not line or line in ("无", "无。", ""):
            continue
        content, _, importance = line.rpartition("|")
        content = content.strip()
        if not content or len(content) < 4:
            continue
        try:
            imp = float(importance.strip())
            imp = max(0.0, min(1.0, imp))
        except ValueError:
            imp = 0.6
        result.append((content, imp))
    return result


async def generate_style_card(
    group_id, llm_client, update_baisuwen_config=None,
) -> Optional[str]:
    """生成群风格卡：最近消息 + 统计 → 结构化 JSON，返回 JSON 字符串"""
    db_path = storage.group_db_path(group_id)
    if not os.path.exists(db_path):
        return None
    msgs = storage.get_recent_messages(db_path, _MAX_STYLE_MSGS)
    if len(msgs) < 20:
        return None
    stats = storage.get_group_stats(db_path)
    topics = "、".join(stats.get("topics", [])[:5]) or "无明显话题"
    sample = []
    for m in msgs[-80:]:
        content = m["content"].replace("\n", " ")[:100]
        sample.append(f"用户{m['user_id']}: {content}")
    prompt = (
        "请分析这个QQ群的整体氛围与说话习惯，输出严格的JSON对象，字段：\n"
        '{"tone": "群氛围一句话描述(如: 轻松玩梗型/安静礼貌型/游戏讨论型/亲友日常型)", '
        '"habits": ["2-3个具体习惯，如: 爱发猫猫表情包、晚上活跃"], '
        '"topics": ["2-3个高频话题"], '
        '"nicknames": {"QQ号": "群内称呼", ...最多3个，无则省略}}\n'
        "已知高频话题：" + topics + "\n"
        "最近消息样本：\n" + chr(10).join(sample)
    )
    try:
        kwargs = {}
        model = _pick_model(update_baisuwen_config)
        if model:
            kwargs["model"] = model
        response = await llm_client.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=300,
            **kwargs,
        )
    except Exception as e:
        logger.debug(f"群风格卡生成失败 [{group_id}]: {e}")
        return None

    # 提取 JSON（兼容 markdown 围栏；反引号用 chr(96) 表示）
    text = response.strip()
    if text.count(chr(96)) >= 6:
        parts = text.split(chr(96))
        text = parts[1] if len(parts) >= 3 else parts[0]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        card = {
            "tone": str(data.get("tone", ""))[:100],
            "habits": [str(h)[:50] for h in data.get("habits", [])[:3]],
            "topics": [str(t)[:50] for t in data.get("topics", [])[:3]],
            "nicknames": {
                str(k): str(v)[:30]
                for k, v in (data.get("nicknames") or {}).items()
            } if isinstance(data.get("nicknames"), dict) else {},
            "updated_at": int(time.time()),
        }
        card_json = json.dumps(card, ensure_ascii=False)
        # 群级别名（检索扩展用）：{主词: [别名...]}，最多 5 组
        raw_aliases = data.get("aliases")
        if isinstance(raw_aliases, dict):
            aliases = {}
            for k, vs in list(raw_aliases.items())[:5]:
                if isinstance(vs, list):
                    cleaned = [str(v)[:20] for v in vs[:3] if str(v).strip()]
                    if cleaned:
                        aliases[str(k)[:20]] = cleaned
            if aliases:
                storage.set_meta(
                    db_path, "aliases",
                    json.dumps(aliases, ensure_ascii=False),
                )
    except Exception as e:
        logger.debug(f"群风格卡解析失败 [{group_id}]: {e}")
        return None
    storage.set_meta(db_path, "style_card", card_json)
    logger.info(f"群风格卡生成完成 [{group_id}]: {card['tone']}")
    return card_json


def retrieve_group_memories(
    group_id, query: str, top_k: int = GROUP_MEMORY_TOP_K,
    extra_aliases: Optional[dict] = None,
) -> list:
    """检索群记忆（复用记忆引擎 FTS5/遗忘曲线 + 群级别名扩展）"""
    db_path = storage.group_db_path(group_id)
    if not os.path.exists(db_path):
        return []
    if extra_aliases is None:
        raw = storage.get_meta(db_path, "aliases", "")
        if raw:
            try:
                extra_aliases = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                extra_aliases = None
    try:
        return retrieve_memories(
            query, top_k=top_k,
            include_short=True, include_long=False,
            update_access=True,
            db_short=db_path, db_long=db_path,
            extra_aliases=extra_aliases,
        )
    except Exception as e:
        logger.debug(f"群记忆检索失败 [{group_id}]: {e}")
        return []
