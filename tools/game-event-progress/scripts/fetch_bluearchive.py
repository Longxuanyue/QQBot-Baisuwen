#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取蔚蓝档案国服官网公告，解析要打的活动时段。"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DATA,
    TZ,
    build_event,
    cache_cover,
    guess_category,
    http_get_json,
    now_cn,
    parse_ranges,
    pick_primary,
    strip_html,
    write_events,
)

LIST_URL = "https://bluearchive-cn.com/api/news/list?pageIndex={page}&pageNum=40&type="
HEADERS = {
    "Referer": "https://bluearchive-cn.com/",
    "Origin": "https://bluearchive-cn.com",
    "Accept": "application/json",
}

# 作战类
COMBAT = re.compile(
    r"限时活动|总力战|大决战|特殊作战|PRAY-BALL|异饼|联合演习|制约决战|无限制决战",
    re.I,
)
# 卡池
GACHA = re.compile(r"限时招募|档案招募", re.I)
# 明确不要的噪音
SKIP = re.compile(
    r"家具|爱用品|功能新增|优化说明|维护|封禁|问卷|直播|周边|创作|指引任务",
    re.I,
)


def short_name(title: str) -> str:
    t = title.strip()
    t = re.sub(r"^【预告】", "", t)
    t = re.sub(r"^限时活动[：:]", "", t)
    t = re.sub(r"^总力战[：:]", "总力战·", t)
    t = re.sub(r"^大决战[：:]", "大决战·", t)
    return t.strip()[:28]


def ba_category(title: str) -> str | None:
    if SKIP.search(title):
        return None
    if GACHA.search(title):
        return "gacha"
    if COMBAT.search(title):
        return "combat"
    if re.search(r"签到|掉落量|登录", title):
        return "event"
    return None


def fetch_pages(max_pages: int = 3) -> list[dict]:
    rows: list[dict] = []
    seen: set[int] = set()
    for page in range(1, max_pages + 1):
        data = http_get_json(LIST_URL.format(page=page), HEADERS)
        batch = data.get("data", {}).get("rows") or []
        if not batch:
            break
        for r in batch:
            rid = int(r["id"])
            if rid in seen:
                continue
            seen.add(rid)
            rows.append(r)
        print(f"[BA] page {page}: +{len(batch)}")
    return rows


def main() -> int:
    now = now_cn()
    rows = fetch_pages(3)
    events = []
    notes = []

    for r in rows:
        title = (r.get("title") or "").strip()
        cat = ba_category(title)
        if not cat:
            notes.append(f"{r.get('id')} 跳过：{title[:40]}")
            continue

        content = strip_html(r.get("content") or "")
        ranges = parse_ranges(content, now)
        primary = pick_primary(ranges)
        if not primary:
            # 预告常只有开启点：XX月XX日 14:00 开启 → 估 7 天窗口
            m = re.search(
                r"(?P<m>\d{1,2})月(?P<d>\d{1,2})日\s*(?P<h>\d{1,2})[:：](?P<min>\d{2})",
                content,
            )
            if not m:
                notes.append(f"{r.get('id')} 无时段：{title[:40]}")
                continue
            y = now.year
            start = datetime(
                y, int(m["m"]), int(m["d"]), int(m["h"]), int(m["min"]), tzinfo=TZ
            )
            if start < now - __import__("datetime").timedelta(days=60):
                start = datetime(
                    y + 1, int(m["m"]), int(m["d"]), int(m["h"]), int(m["min"]), tzinfo=TZ
                )
            end = start + __import__("datetime").timedelta(days=7)
            primary = {
                "label": "估时（仅有开启点）",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "raw": m.group(0),
            }
            ranges = [primary]
            fuzzy = True
        else:
            fuzzy = "估" in primary.get("label", "")
            start = datetime.fromisoformat(primary["start"])
            end = datetime.fromisoformat(primary["end"])

        # 已结束太久 / 离谱超远期（解析串年）丢掉
        if end < now - __import__("datetime").timedelta(days=3):
            notes.append(f"{r.get('id')} 已过期：{title[:40]}")
            continue
        if start > now + __import__("datetime").timedelta(days=60):
            notes.append(f"{r.get('id')} 超远期跳过：{title[:40]}")
            continue

        cid = str(r["id"])
        banner = cache_cover(f"ba-{cid}", r.get("banner") or "", "https://bluearchive-cn.com/")
        name = short_name(title)
        kind = "preview" if title.startswith("【预告】") or start > now else "live"
        ev = build_event(
            cid=cid,
            title=title,
            header=f"「{name}」",
            banner=banner,
            link=f"https://bluearchive-cn.com/news/{cid}",
            start=start,
            end=end,
            ranges=ranges,
            kind=kind,
            fuzzy=fuzzy,
            category=cat or guess_category(title),
            summary=(content[:160] + "…") if len(content) > 160 else content,
        )
        events.append(ev)
        safe = name.replace("\u2022", "·").replace("•", "·")
        print(f"  + [{ev['status']}] {safe} | {ev['remain']}")

    # 进行中优先，再预告
    rank = {"进行中": 0, "即将开始": 1, "已结束": 2}
    events.sort(key=lambda e: (rank.get(e["status"], 9), e.get("start") or ""))

    payload = {
        "game": "蔚蓝档案",
        "source": "https://bluearchive-cn.com/api/news/list",
        "fetchedAt": now.isoformat(),
        "timezone": "Asia/Shanghai",
        "count": len(events),
        "notes": notes[:40],
        "events": events,
    }
    write_events(DATA / "bluearchive.json", payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
