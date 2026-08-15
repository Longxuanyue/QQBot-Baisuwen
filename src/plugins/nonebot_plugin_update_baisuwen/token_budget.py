"""
Token 预算管理：粗略估算、按预算截断、对话历史裁剪。

原则：
- 估算不追求精确（避免引入 tiktoken 等重依赖），只需保证"大致不超窗"，
  并配合 max_tokens 上限形成双重保险。
- 裁剪优先级：最旧的历史消息 > system prompt 尾部内容。
"""

import re

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")

# 消息角色开销与系统截断下限
_ROLE_OVERHEAD_TOKENS = 4
_MIN_SYSTEM_TOKENS = 64
_MIN_TRUNCATE_TOKENS = 20
_MIN_MESSAGE_COUNT = 2
_BUDGET_MARGIN_TOKENS = 16
_ELLIPSIS_TOKENS = 8


def estimate_tokens(text: str) -> int:
    """粗略估算文本 token 数：中文按 ~0.9 token/字，其他按 4 字符/token。"""
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    other = len(text) - cjk
    return max(1, int(cjk * 0.9 + other / 4))


def estimate_messages_tokens(messages: list[dict]) -> int:
    """估算一组消息的总 token 数（含每条的角色开销）。"""
    return sum(
        estimate_tokens(m.get("content", "")) + _ROLE_OVERHEAD_TOKENS
        for m in messages
    )


def _fit_prefix_len(text: str, max_tokens: int) -> int:
    """二分查找满足预算的最长前缀长度（中文按 ~0.9 token/字 估算）"""
    if max_tokens <= 0 or not text:
        return 0
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if estimate_tokens(text[:mid]) <= max_tokens:
            lo = mid
        else:
            hi = mid - 1
    return lo


def truncate_text(text: str, max_tokens: int) -> str:
    """按 token 预算截断文本：保留开头与结尾，中间用省略标记。"""
    if not text or max_tokens <= 0:
        return ""
    if estimate_tokens(text) <= max_tokens:
        return text
    if max_tokens <= _MIN_TRUNCATE_TOKENS:
        return text[:_fit_prefix_len(text, max_tokens)]
    head_tokens = max(1, (max_tokens - _ELLIPSIS_TOKENS) // 2)
    tail_tokens = max(1, max_tokens - _ELLIPSIS_TOKENS - head_tokens)
    head_len = _fit_prefix_len(text, head_tokens)
    tail_len = _fit_prefix_len(text[::-1], tail_tokens)
    if head_len + tail_len >= len(text):
        # 估算误差兜底：只保留满足预算的前缀
        return text[:_fit_prefix_len(text, max_tokens)]
    return (
        text[:head_len]
        + "\n……（已截断）……\n"
        + text[len(text) - tail_len:]
    )


def _last_user_index(messages: list[dict]) -> int:
    """最后一条 user 消息的下标（没有则返回 -1）"""
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            return i
    return -1


def _drop_oldest(messages: list[dict]) -> bool:
    """移除最早的一条非 system、非最后一条 user 的消息。返回是否移除成功。"""
    last_user = _last_user_index(messages)
    for i in range(len(messages)):
        if messages[i].get("role") == "system" or i == last_user:
            continue
        messages.pop(i)
        return True
    return False


def trim_messages(messages: list[dict], max_tokens: int) -> list[dict]:
    """将消息列表裁剪到预算内。

    保留策略（按优先级）：
    1. system 消息（人设等）——最后兜底截断其内容
    2. 最后一条 user 消息（当前提问）
    3. 越新的历史越优先保留
    """
    if not messages:
        return messages
    if estimate_messages_tokens(messages) <= max_tokens:
        return messages

    result = list(messages)
    # 从最旧开始逐条移除非 system、非最后一条 user 的消息
    while (
        estimate_messages_tokens(result) > max_tokens
        and len(result) > _MIN_MESSAGE_COUNT
    ):
        if not _drop_oldest(result):
            break

    if estimate_messages_tokens(result) <= max_tokens:
        return result

    # 仍超预算：截断 system 内容（保人设主体，去尾部附加信息）
    sys_idx = next(
        (i for i, m in enumerate(result) if m.get("role") == "system"), None
    )
    if sys_idx is not None:
        others = sum(
            estimate_tokens(m.get("content", ""))
            for i, m in enumerate(result)
            if i != sys_idx
        )
        sys_budget = max(
            _MIN_SYSTEM_TOKENS, max_tokens - others - _BUDGET_MARGIN_TOKENS
        )
        result[sys_idx] = {
            **result[sys_idx],
            "content": truncate_text(result[sys_idx]["content"], sys_budget),
        }
    return result
