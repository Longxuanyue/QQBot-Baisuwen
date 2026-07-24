#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取米哈游系游戏内公告（原神 / 星铁 / 绝区零）。"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DATA,
    TZ,
    build_event,
    cache_cover,
    guess_category,
    http_get_json,
    is_bare_announce,
    now_cn,
    write_events,
)

# 星铁公告 API 不单独发跃迁，用公开日历补卡池
STARRAIL_CALENDAR = "https://api.ennead.cc/mihoyo/starrail/calendar"

GAMES = [
    {
        "id": "genshin",
        "name": "原神",
        "file": "genshin.json",
        "list": (
            "https://hk4e-api.mihoyo.com/common/hk4e_cn/announcement/api/getAnnList"
            "?game=hk4e&game_biz=hk4e_cn&lang=zh-cn&bundle_id=hk4e_cn"
            "&platform=pc&region=cn_gf01&level=55&uid=100000000"
        ),
        "referer": "https://ys.mihoyo.com/",
    },
    {
        "id": "starrail",
        "name": "崩坏：星穹铁道",
        "file": "starrail.json",
        "list": (
            "https://hkrpg-api.mihoyo.com/common/hkrpg_cn/announcement/api/getAnnList"
            "?game=hkrpg&game_biz=hkrpg_cn&lang=zh-cn&bundle_id=hkrpg_cn"
            "&platform=pc&region=prod_gf_cn&level=70&uid=100000000"
        ),
        "referer": "https://sr.mihoyo.com/",
    },
    {
        "id": "zzz",
        "name": "绝区零",
        "file": "zzz.json",
        "list": (
            "https://announcement-api.mihoyo.com/common/nap_cn/announcement/api/getAnnList"
            "?game=nap&game_biz=nap_cn&lang=zh-cn&bundle_id=nap_cn"
            "&platform=pc&region=prod_gf_cn&level=60&uid=100000000"
        ),
        "referer": "https://zzz.mihoyo.com/",
    },
]

SKIP = re.compile(
    r"问卷|封禁|客服|未成年人|防沉迷|适龄提示|版本更新说明|修复与优化|已知问题|"
    r"公平运营|防诈骗|FAQ|社区中心|官网|用户协议|个人信息|隐私|兑换码|"
    r"官方社媒|小程序|米游社|微博|抖音|Bilibili|媒体合页|"
    r"维护预告|更新公告|征集|战绩更新|生日贺礼",
    re.I,
)


def clean_title(t: str) -> str:
    t = unescape(t or "")
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def classify(title: str, subtitle: str, tag: str, type_label: str) -> str:
    blob = f"{title} {subtitle} {tag} {type_label}"
    if re.search(r"祈愿|跃迁|调频|卡池|UP|特选|常驻", blob, re.I):
        return "gacha"
    if re.search(r"危战|深渊|剧情|活动说明|作战|挑战|深境|逐光|模拟宇宙|差分宇宙|空洞|零号空洞|战线", blob, re.I):
        return "combat"
    if type_label and "活动" in type_label and not re.search(r"维护|更新|修复", blob):
        # 活动公告里再分
        if re.search(r"签到|兑换|商城|特卖|赠礼|邮件", blob):
            return "event"
        if re.search(r"祈愿|跃迁|调频", blob):
            return "gacha"
        return "combat"
    return guess_category(title, subtitle, type_label)


def parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=TZ)
        except ValueError:
            continue
    return None


def _ts_to_dt(ts: int | float | str | None) -> datetime | None:
    if ts in (None, "", 0, "0"):
        return None
    try:
        n = int(float(ts))
    except (TypeError, ValueError):
        return None
    if n > 1e12:
        n //= 1000
    if n < 1_500_000_000:
        return None
    try:
        return datetime.fromtimestamp(n, tz=TZ)
    except (OSError, OverflowError, ValueError):
        return None


def fetch_starrail_banners(now: datetime, notes: list[str]) -> list[dict]:
    """公告无跃迁时段时，从公开日历补角色/光锥池。"""
    out: list[dict] = []
    try:
        cal = http_get_json(STARRAIL_CALENDAR, {"Accept": "application/json"})
    except Exception as e:
        notes.append(f"跃迁日历失败: {e}")
        return out
    for b in cal.get("banners") or []:
        start = _ts_to_dt(b.get("start_time"))
        end = _ts_to_dt(b.get("end_time"))
        if not start:
            continue
        if not end or end <= start:
            # 联动池偶发无截止：估 21 天
            end = start + timedelta(days=21)
        if end < now:
            continue
        if (end - start).days > 80:
            continue
        chars = b.get("characters") or []
        cones = b.get("light_cones") or b.get("weapons") or []
        names = [c.get("name") for c in chars if c.get("name")]
        names += [c.get("name") for c in cones if c.get("name")]
        name = (b.get("name") or "").strip()
        if not name:
            name = " / ".join(names[:3]) if names else "活动跃迁"
        # 日历多为英文名：有角色名单时优先用名单做短标题
        if names and (not name or re.search(r"[A-Za-z]{3,}", name)):
            short = " / ".join(names[:2])
            header = f"跃迁·{short}"
        else:
            header = f"跃迁·{name}"
        title = header
        icon = ""
        for c in chars + cones:
            if c.get("icon"):
                icon = c["icon"]
                break
        if not icon:
            icon = b.get("image_url") or b.get("image") or ""
        cid = f"sr-banner-{b.get('id') or name}"
        banner = cache_cover(f"starrail-{cid}", icon, "https://www.hoyolab.com/") if icon else ""
        out.append(
            build_event(
                cid=str(cid),
                title=title,
                header=header,
                banner=banner,
                link="https://sr.mihoyo.com/",
                start=start,
                end=end,
                category="gacha",
                summary=" / ".join(names[:6]) or name,
            )
        )
        print(f"  + [gacha][{out[-1]['status']}] {header[:28]} {out[-1]['remain']}")
    if out:
        notes.append(f"日历补跃迁 {len(out)} 条")
    return out


def fetch_game(cfg: dict) -> int:
    now = now_cn()
    print(f"[hoyo] {cfg['name']}")
    data = http_get_json(cfg["list"], {"Referer": cfg["referer"], "Accept": "application/json"})
    if data.get("retcode") not in (0, "0", None) and data.get("retcode") != 0:
        print("  fail", data.get("message"))
        return 1

    events = []
    notes = []
    for group in data.get("data", {}).get("list") or []:
        type_label = group.get("type_label") or ""
        for a in group.get("list") or []:
            title = clean_title(a.get("title") or "")
            subtitle = clean_title(a.get("subtitle") or "")
            if not title or SKIP.search(title) or is_bare_announce(title):
                notes.append(f"跳过 {title[:40]}")
                continue
            # 版本总览类常无封面且与具体活动重复
            if re.search(r"全新内容一览|版本内容一览", title):
                notes.append(f"跳过总览 {title[:36]}")
                continue
            start = parse_dt(a.get("start_time") or "")
            end = parse_dt(a.get("end_time") or "")
            if not start or not end or end <= start:
                continue
            if end < now:
                continue  # 只要进行中/预告
            # 丢掉跨度过大的常驻说明（运营规范等）
            if (end - start).days > 80:
                notes.append(f"常驻跳过 {title[:36]}")
                continue

            cat = classify(title, subtitle, a.get("tag_label") or "", type_label)
            if cat == "other":
                cat = "event"
            cid = str(a.get("ann_id"))
            banner = a.get("banner") or ""
            if banner:
                banner = cache_cover(f"{cfg['id']}-{cid}", banner, cfg["referer"])
            header = f"「{subtitle or title[:18]}」" if subtitle else title
            ev = build_event(
                cid=cid,
                title=title,
                header=header,
                banner=banner,
                link=cfg["referer"],
                start=start,
                end=end,
                category=cat,
                summary=subtitle or title,
            )
            events.append(ev)

    if cfg["id"] == "starrail":
        events.extend(fetch_starrail_banners(now, notes))

    # 去重
    seen = set()
    uniq = []
    for e in events:
        key = (e["title"], e["start"], e["end"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(e)

    rank = {"进行中": 0, "即将开始": 1, "已结束": 2}
    cat_rank = {"combat": 0, "gacha": 1, "event": 2, "web": 3}
    uniq.sort(
        key=lambda e: (
            rank.get(e["status"], 9),
            cat_rank.get(e.get("category", "event"), 9),
            e.get("start") or "",
        )
    )

    source = cfg["list"].split("?")[0]
    if cfg["id"] == "starrail":
        source = f"{source} + {STARRAIL_CALENDAR}"

    write_events(
        DATA / cfg["file"],
        {
            "game": cfg["name"],
            "source": source,
            "fetchedAt": now.isoformat(),
            "timezone": "Asia/Shanghai",
            "count": len(uniq),
            "notes": notes[:30],
            "events": uniq,
        },
    )
    for e in uniq[:8]:
        print(f"  + [{e['category']}][{e['status']}] {e['header'][:24]} {e['remain']}")
    return 0


def main() -> int:
    codes = [fetch_game(g) for g in GAMES]
    return 1 if any(codes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
