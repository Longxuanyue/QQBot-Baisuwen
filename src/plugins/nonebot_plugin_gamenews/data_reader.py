"""
数据读取层 —— 从 tools/game-event-progress/data/*.json 加载事件数据。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from nonebot import logger

from .config import plugin_config
from .games import GAME_KEYS, GAMES, GAME_NAMES, GAME_EMOJIS

TZ = timezone(timedelta(hours=8))

# ── 分类标签映射 ──
CAT_LABELS: dict[str, str] = {
    "combat": "作战",
    "gacha": "卡池",
    "event": "活动",
    "web": "网页",
}
CAT_ORDER = {"combat": 0, "gacha": 1, "web": 2, "event": 3}


def _data_dir() -> Path:
    return Path(plugin_config.game_event_data_dir)


def _covers_dir() -> Path:
    return Path(plugin_config.game_event_covers_dir)


def _resolve_cover(banner: str) -> str:
    """将相对路径 ./covers/xxx 转为绝对路径。"""
    if not banner:
        return ""
    if banner.startswith("./covers/"):
        fname = banner.split("/")[-1]
        abs_path = _covers_dir() / fname
        return str(abs_path) if abs_path.exists() else ""
    if banner.startswith("http"):
        return banner
    return ""


def now_cn() -> datetime:
    return datetime.now(TZ)


def _parse_dt(s: str | None) -> datetime | None:
    """解析 ISO 时间字符串。"""
    if not s:
        return None
    try:
        # 处理 +08:00 格式
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


# ── 常驻周期活动（不依赖抓取，按固定规则计算起止） ──

PERMANENT_CYCLES: dict[str, list[dict[str, Any]]] = {
    "arknights": [
        {
            "event_id": "perm_ak_annihilation",
            "title": "剿灭作战 · 周常奖励刷新",
            "event_type": "permanent_cycle",
            "category": "combat",
            "cycle_days": 7,
            "cycle_anchor": datetime(2024, 1, 1, 4, 0, 0, tzinfo=TZ),  # 周一04:00
            "description": "每周一04:00 剿灭合成玉奖励刷新",
        },
    ],
}


def _generate_cycle_event(cfg: dict[str, Any], game_key: str) -> dict[str, Any]:
    """根据周期配置生成一条活动事件（含当前周期的起止/进度/剩余）。"""
    now = now_cn()
    anchor: datetime = cfg["cycle_anchor"]
    days: int = cfg["cycle_days"]

    # 计算当前周期窗口
    delta = now - anchor
    cycles_elapsed = delta.total_seconds() / (days * 86400)
    current_cycle_start = anchor + timedelta(days=days * int(cycles_elapsed))
    current_cycle_end = current_cycle_start + timedelta(days=days)

    # 如果当前时间已经过了窗口末尾（通常不会），推到下一个窗口
    if now >= current_cycle_end:
        current_cycle_start = current_cycle_end
        current_cycle_end = current_cycle_start + timedelta(days=days)

    total_sec = (current_cycle_end - current_cycle_start).total_seconds()
    elapsed_sec = (now - current_cycle_start).total_seconds()
    remain_sec = (current_cycle_end - now).total_seconds()
    pct = max(0.0, min(100.0, elapsed_sec / total_sec * 100))

    remain_days = int(remain_sec // 86400)
    remain_hours = int((remain_sec % 86400) // 3600)
    if remain_days > 0:
        remain_text = f"剩{remain_days}天{remain_hours}时"
    else:
        remain_text = f"剩{remain_hours}小时"

    elapsed_days = round(elapsed_sec / 86400, 1)
    remain_days_f = round(remain_sec / 86400, 1)

    meta = GAMES.get(game_key)
    return {
        "id": cfg["event_id"],
        "title": cfg["title"],
        "header": cfg["title"],
        "banner": "",
        "link": "",
        "start": current_cycle_start.isoformat(),
        "end": current_cycle_end.isoformat(),
        "status": "进行中",
        "remain": remain_text,
        "progress": round(pct, 1),
        "days": {
            "elapsedDays": elapsed_days,
            "remainDays": remain_days_f,
            "totalDays": float(days),
        },
        "hasSchedule": True,
        "kind": "live",
        "fuzzy": False,
        "category": cfg["category"],
        "event_type": cfg["event_type"],
        "allRanges": [],
        "summary": cfg["description"],
        "_game_key": game_key,
        "_game_name": GAME_NAMES.get(game_key, game_key),
        "_game_emoji": GAME_EMOJIS.get(game_key, "🎮"),
        "_game_color": meta.color if meta else "#f0c41a",
        "_cover_abs": "",
        "_is_permanent": True,
    }


def _inject_permanent_cycles(game_key: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """向事件列表注入常驻周期活动。"""
    cycles = PERMANENT_CYCLES.get(game_key, [])
    if not cycles:
        return events
    for cfg in cycles:
        events.append(_generate_cycle_event(cfg, game_key))
    return events


def load_status() -> dict[str, Any]:
    """读取更新状态。"""
    path = _data_dir() / "status.json"
    if not path.exists():
        return {"updatedAt": None, "fetchOk": False}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"updatedAt": None, "fetchOk": False}


# 某些游戏的 JSON 文件名与 key 不同
_FILENAME_OVERRIDE: dict[str, str] = {
    "arknights": "events.json",  # 明日方舟写作 events.json
}


def _data_path_for(game_key: str) -> Path:
    """获取游戏数据文件路径（处理特殊文件名映射）。"""
    fname = _FILENAME_OVERRIDE.get(game_key, f"{game_key}.json")
    return _data_dir() / fname


def load_game_events(game_key: str) -> dict[str, Any] | None:
    """读取单个游戏的事件数据（自动附加 _game_* 元数据字段）。"""
    path = _data_path_for(game_key)
    if not path.exists():
        logger.warning(f"[GameNews] 数据文件不存在: {path}")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error(f"[GameNews] 读取失败 {path}: {exc}")
        return None

    # 附加游戏元数据到每个事件
    meta = GAMES.get(game_key)
    emoji = GAME_EMOJIS.get(game_key, "🎮")
    name = GAME_NAMES.get(game_key, game_key)
    color = meta.color if meta else "#f0c41a"

    for ev in data.get("events", []):
        ev["_game_key"] = game_key
        ev["_game_name"] = name
        ev["_game_emoji"] = emoji
        ev["_game_color"] = color
        ev["_cover_abs"] = _resolve_cover(ev.get("banner", ""))

    # 注入常驻周期活动（如剿灭作战）
    events = data.get("events", [])
    data["events"] = _inject_permanent_cycles(game_key, list(events))

    return data


def load_all_events(
    *,
    include_preview: bool = True,
    only_active: bool = True,
) -> list[dict[str, Any]]:
    """加载白名单全部游戏的活动事件，返回统一扁平列表。

    每个事件附加 _game_key、_game_name、_game_emoji、_game_color、_cover_abs 字段。
    """
    all_events: list[dict[str, Any]] = []
    now = now_cn()

    for key in GAME_KEYS:
        data = load_game_events(key)
        if not data:
            continue

        meta = GAMES[key]
        for ev in data.get("events", []):
            # 过滤已结束
            if only_active and ev.get("status") == "已结束":
                continue
            # 过滤预告
            if not include_preview and ev.get("status") == "即将开始":
                continue

            ev["_game_key"] = key
            ev["_game_name"] = meta.name
            ev["_game_emoji"] = meta.emoji
            ev["_game_color"] = meta.color
            ev["_cover_abs"] = _resolve_cover(ev.get("banner", ""))
            all_events.append(ev)

    # 排序：游戏顺序 → 分类（作战>卡池>网页>活动）→ 结束时间
    all_events.sort(key=lambda e: (
        GAME_KEYS.index(e["_game_key"]) if e["_game_key"] in GAME_KEYS else 99,
        CAT_ORDER.get(e.get("category", "event"), 99),
        e.get("end", "9") or "9",
    ))
    return all_events


def group_events_by_game(
    events: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """将事件按游戏分组，返回 {game_key: {meta, events}}。"""
    grouped: dict[str, dict[str, Any]] = {}
    for ev in events:
        key = ev["_game_key"]
        if key not in grouped:
            grouped[key] = {
                "key": key,
                "name": ev["_game_name"],
                "emoji": ev["_game_emoji"],
                "color": ev["_game_color"],
                "events": [],
            }
        grouped[key]["events"].append(ev)
    return grouped


def filter_by_category(
    events: list[dict[str, Any]], category: str,
) -> list[dict[str, Any]]:
    """按类别筛选事件。category: combat/gacha/event/web"""
    return [e for e in events if e.get("category") == category]


def get_urgent_events(
    hours: int | None = None,
) -> list[dict[str, Any]]:
    """获取即将截止的事件（end 在指定小时内）。"""
    hours = hours or plugin_config.urgency_hours
    all_ev = load_all_events(include_preview=False, only_active=True)
    now = now_cn()
    threshold = now + timedelta(hours=hours)

    urgent: list[dict[str, Any]] = []
    for ev in all_ev:
        end = _parse_dt(ev.get("end"))
        if end and now < end <= threshold:
            ev["_urgent_hours_left"] = round((end - now).total_seconds() / 3600, 1)
            urgent.append(ev)

    urgent.sort(key=lambda e: e.get("end", ""))
    return urgent


def format_updated_time() -> str:
    """格式化数据更新时间。"""
    status = load_status()
    updated = status.get("updatedAt")
    if not updated:
        return "未知"
    try:
        dt = datetime.fromisoformat(updated)
        return dt.strftime("%m-%d %H:%M")
    except (ValueError, TypeError):
        return str(updated)[:16]
