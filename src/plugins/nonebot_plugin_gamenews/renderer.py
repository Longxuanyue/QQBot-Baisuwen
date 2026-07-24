"""
HTML 渲染引擎 —— Jinja2 模板 + nonebot_plugin_htmlrender 截图。

将活动/卡池/公告数据渲染为图片 bytes，可直接通过 QQ Bot 发送。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import jinja2
from nonebot import logger

from .config import plugin_config

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_env = jinja2.Environment(
    extensions=["jinja2.ext.loopcontrols"],
    loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
    enable_async=False,
)

# 分类标签
CAT_LABELS = {"combat": "作战", "gacha": "卡池", "event": "活动", "web": "网页"}


def _render_html(template_name: str, **kwargs) -> str:
    """渲染 Jinja2 模板为 HTML 字符串。"""
    tpl = _env.get_template(template_name)
    return tpl.render(
        width=plugin_config.render_width,
        cat_labels=CAT_LABELS,
        **kwargs,
    )


async def html_to_image(html: str) -> bytes:
    """将 HTML 字符串渲染为 PNG 图片。"""
    try:
        from nonebot_plugin_htmlrender import html_to_pic
        return await html_to_pic(
            html=html,
            viewport={"width": plugin_config.render_width, "height": 100},
            type="png",
            device_scale_factor=plugin_config.device_scale_factor,
        )
    except ImportError:
        logger.error("[GameNews] nonebot_plugin_htmlrender 未安装")
        raise
    except Exception as exc:
        logger.error(f"[GameNews] 渲染失败: {exc}")
        raise


async def render_events_image(
    events: list[dict[str, Any]],
    title: str,
    subtitle: str = "",
    updated: str = "",
    *,
    mark_urgent: bool = False,
) -> bytes:
    """将事件列表渲染为活动进度图片。

    Args:
        events: 已附加 _game_* 字段的事件列表
        title: 标题（如「进行中活动」）
        subtitle: 副标题
        updated: 数据更新时间
        mark_urgent: 是否标记紧迫事件
    """
    from .data_reader import group_events_by_game

    if mark_urgent:
        from datetime import datetime, timedelta, timezone
        TZ = timezone(timedelta(hours=8))
        now = datetime.now(TZ)
        threshold = now + timedelta(hours=plugin_config.urgency_hours)
        for ev in events:
            if ev.get("end"):
                try:
                    end_dt = datetime.fromisoformat(ev["end"])
                    ev["_urgent"] = end_dt <= threshold
                except (ValueError, TypeError):
                    ev["_urgent"] = False
            else:
                ev["_urgent"] = False

    grouped = group_events_by_game(events)
    html = _render_html(
        "events.html",
        title=title,
        subtitle=subtitle,
        updated=updated,
        grouped=grouped,
    )
    return await html_to_image(html)


async def render_urgent_image(
    urgent_events: list[dict[str, Any]],
    updated: str = "",
) -> bytes:
    """渲染紧迫提醒图片。"""
    html = _render_html(
        "urgent.html",
        events=urgent_events,
        updated=updated,
        hours=plugin_config.urgency_hours,
    )
    return await html_to_image(html)


async def render_daily_push_image(
    all_events: list[dict[str, Any]],
    updated: str = "",
) -> bytes:
    """渲染每日综合推送图片（全部进行中/预告事件）。"""
    return await render_events_image(
        all_events,
        title="活动进度 · 每日速报",
        subtitle="作战 · 卡池 · 活动 · 网页",
        updated=updated,
        mark_urgent=True,
    )
