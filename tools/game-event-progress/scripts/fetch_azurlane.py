#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从碧蓝航线 Bwiki「港区改建」公告解析限时活动 / 建造。"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DATA,
    TZ,
    build_event,
    cache_cover,
    http_get_json,
    make_dt,
    now_cn,
    write_events,
)

API = "https://wiki.biligame.com/blhx/api.php"
UA = {"User-Agent": "Mozilla/5.0 GameEventCal/1.1", "Accept": "application/json"}
LINK_BASE = "https://wiki.biligame.com/blhx/"
CACHE = DATA / "cache" / "azurlane"

TITLE_RE = re.compile(r"^(?P<y>20\d{2})年(?P<m>\d{1,2})月(?P<d>\d{1,2})日(?P<h>\d{1,2}):(?P<mi>\d{2})港区改建$")

# 开启限时大型活动'''复刻：绽放于辉光之城'''，活动时间6月18日维护后~6月25日维护前
# 开启限时活动「远航回礼」（7月9日维护后~7月22日23:59）
EVENT_RE = re.compile(
    r"(?P<label>开启限时大型活动|开启限时联动复刻活动|开启限时联动活动|开启限时复刻活动|"
    r"开启限时特殊活动|开启限时活动|开启新一期|开启下一期|开启活动|复刻[：:])\s*"
    r"[「『\"]?(?P<name>[^」』\"\n]{2,48}?)[」』\"]?"
    r"(?:活动)?"
    r"(?:"
    r"[，,]\s*活动时间(?P<span1>[^。\n；;]{6,80})"
    r"|"
    r"[（(](?P<span2>[^）)\n]{6,80})[）)]"
    r")",
)

# 限时建造期间 / 开启限时建造
BUILD_RE = re.compile(
    r"(?P<label>限时建造|限时重返建造)"
    r"[^。\n]{0,60}?"
    r"(?:"
    r"活动时间(?P<span1>[^。\n]{6,60})"
    r"|"
    r"[（(](?P<span2>[^）)\n]{6,60})[）)]"
    r")",
)

# 「科研」之类不算
SKIP = re.compile(r"礼包|换装商店|优惠|研发礼包|兑换商店|家具|抵扣")


def wiki_json(params: dict, retries: int = 4) -> dict:
    q = urllib.parse.urlencode({**params, "format": "json"})
    url = f"{API}?{q}"
    last: Exception | None = None
    for i in range(retries):
        try:
            return http_get_json(url, UA)
        except HTTPError as e:
            last = e
            # 567 / 429 等限流
            time.sleep(1.2 * (i + 1))
        except Exception as e:
            last = e
            time.sleep(0.8 * (i + 1))
    raise last or RuntimeError("wiki_json failed")


def list_rebuild_pages(year: int = 2026) -> list[str]:
    def key(t: str):
        m = TITLE_RE.match(t)
        return tuple(int(m[k]) for k in ("y", "m", "d", "h", "mi"))

    titles: list[str] = []
    try:
        pages = wiki_json(
            {"action": "query", "list": "allpages", "apprefix": f"{year}年", "aplimit": "max"}
        ).get("query", {}).get("allpages", [])
        titles = [p["title"] for p in pages if "港区改建" in p["title"] and TITLE_RE.match(p["title"])]
    except Exception as e:
        print(f"  [warn] 列表失败，改用本地缓存: {e}")

    if CACHE.exists():
        for p in CACHE.glob("*.txt"):
            # 文件名还原不完全，读首行或用已知模式扫描目录旁 metadata
            pass

    # 已知近期维护（wiki 限流时兜底）
    fallback = [
        f"{year}年5月28日10:00港区改建",
        f"{year}年6月5日10:00港区改建",
        f"{year}年6月12日10:00港区改建",
        f"{year}年6月18日10:00港区改建",
        f"{year}年6月25日10:00港区改建",
        f"{year}年7月9日10:00港区改建",
        f"{year}年7月16日10:00港区改建",
    ]
    for t in fallback:
        if TITLE_RE.match(t) and t not in titles:
            titles.append(t)

    titles = [t for t in titles if TITLE_RE.match(t)]
    titles.sort(key=key)
    return titles


def cache_path(title: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", title)
    return CACHE / f"{safe}.txt"


def page_wikitext(title: str, *, refresh: bool = False) -> str:
    from common import http_get

    cached = cache_path(title)
    if cached.exists() and cached.stat().st_size > 100 and not refresh:
        return cached.read_text(encoding="utf-8")

    url = "https://wiki.biligame.com/blhx/index.php?" + urllib.parse.urlencode(
        {"title": title, "action": "raw"}
    )
    try:
        text = http_get(url, UA, timeout=12).decode("utf-8", "replace")
        if len(text) > 200:
            cached.write_text(text, encoding="utf-8")
            return text
    except Exception as e:
        if cached.exists() and cached.stat().st_size > 100:
            print(f"  [cache] {title}")
            return cached.read_text(encoding="utf-8")
        raise e
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    return ""


def page_banner(title: str) -> str:
    data = wiki_json({"action": "parse", "page": title, "prop": "images"})
    images = data.get("parse", {}).get("images") or []
    prefer = next((i for i in images if re.search(r"banner|Banner|活动|专题", i, re.I)), None)
    name = prefer or (images[0] if images else None)
    if not name:
        return ""
    info = wiki_json(
        {
            "action": "query",
            "titles": f"File:{name}",
            "prop": "imageinfo",
            "iiprop": "url",
        }
    )
    pages = info.get("query", {}).get("pages") or {}
    for p in pages.values():
        ii = (p.get("imageinfo") or [{}])[0]
        return ii.get("url") or ""
    return ""


def maint_from_title(title: str) -> datetime:
    m = TITLE_RE.match(title)
    assert m
    return make_dt(int(m["y"]), int(m["m"]), int(m["d"]), int(m["h"]), int(m["mi"]))


def maint_end_from_text(text: str, start: datetime) -> datetime:
    m = re.search(
        rf"{start.month}月{start.day}日\s*{start.hour}:\d{{2}}\s*[~～\-–—至到]\s*"
        rf"(?:{start.month}月{start.day}日\s*)?(?P<h>\d{{1,2}})[:：](?P<mi>\d{{2}})",
        text,
    )
    if m:
        return make_dt(start.year, start.month, start.day, int(m["h"]), int(m["mi"]))
    return start + timedelta(hours=5)


def parse_span(
    span: str,
    maint_start: datetime,
    maint_end: datetime,
    next_maint: datetime | None = None,
) -> tuple[datetime, datetime] | None:
    span = span.strip().replace(" ", "")
    y = maint_start.year

    def one_side(s: str, *, is_start: bool) -> datetime | None:
        s = s.strip()
        if "维护后" in s:
            return maint_end
        m_day = re.search(r"(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日", s)
        # 「7月30日维护」→ 当天 10:00（港区常规维护点）
        if m_day and re.search(r"维护", s):
            yy = int(m_day.group(1) or y)
            return make_dt(yy, int(m_day.group(2)), int(m_day.group(3)), 10, 0)
        if "维护前" in s or s.strip() in ("维护", "维护前"):
            return next_maint or maint_start
        m = re.search(
            r"(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日(?:\s*(\d{1,2})[:：](\d{2}))?",
            s,
        )
        if not m:
            return None
        yy = int(m.group(1) or y)
        hh = int(m.group(4) if m.group(4) is not None else (0 if is_start else 23))
        mi = int(m.group(5) if m.group(5) is not None else (0 if is_start else 59))
        return make_dt(yy, int(m.group(2)), int(m.group(3)), hh, mi)

    parts = re.split(r"[~～\-–—至到]+", span)
    if len(parts) < 2:
        return None
    start = one_side(parts[0], is_start=True)
    end = one_side(parts[1], is_start=False)
    if not start or not end:
        return None
    if end <= start:
        end = make_dt(end.year + 1, end.month, end.day, end.hour, end.minute)
    hours = (end - start).total_seconds() / 3600
    if hours < 1 or hours > 24 * 120:
        return None
    return start, end


def clean_name(name: str) -> str:
    name = re.sub(r"'{2,}", "", name)
    name = re.sub(r"\{\{[^}]+\}\}", "", name)
    name = re.sub(r"\[\[([^|\]]+\|)?([^\]]+)\]\]", r"\2", name)
    name = re.sub(r"<[^>]+>", "", name)
    name = re.sub(r"^活动", "", name)
    name = name.strip(" ：:·-—「」『』")
    return name[:32]


def al_category(label: str, name: str) -> str:
    blob = f"{label} {name}"
    if re.search(r"建造|祈愿建造", blob):
        return "gacha"
    if re.search(r"大型|复刻|海域|作战|EX|SP|档案|限界挑战|同盟|人形之旅", blob):
        return "combat"
    if re.search(r"回礼|登录|签到|累计|巡游|巡演|竞拍|任务|联动|公益", blob):
        return "event"
    return "event"


def parse_page(title: str, next_title: str | None = None) -> list[dict]:
    wt = page_wikitext(title)
    text = re.sub(r"\{\{[^{}]+\}\}", " ", wt)
    text = re.sub(r"\[\[File:[^\]]+\]\]", " ", text)
    maint_start = maint_from_title(title)
    maint_end = maint_end_from_text(wt, maint_start)
    next_maint = maint_from_title(next_title) if next_title and TITLE_RE.match(next_title) else None
    out: list[dict] = []

    for m in EVENT_RE.finditer(text):
        name = clean_name(m.group("name"))
        span = (m.group("span1") or m.group("span2") or "").strip()
        if not name or not span or SKIP.search(name):
            continue
        if "活动专题" in name or name.startswith("{{"):
            continue
        pair = parse_span(span, maint_start, maint_end, next_maint)
        if not pair:
            continue
        start, end = pair
        if "维护前" in span and next_maint and end <= start:
            end = next_maint
        label = m.group("label")
        out.append(
            {
                "name": name,
                "label": label,
                "start": start,
                "end": end,
                "category": al_category(label, name),
                "page": title,
            }
        )

    for m in BUILD_RE.finditer(text):
        if SKIP.search(m.group(0)):
            continue
        span = (m.group("span1") or m.group("span2") or "").strip()
        if not span:
            continue
        pair = parse_span(span, maint_start, maint_end, next_maint)
        if not pair:
            continue
        start, end = pair
        window = text[max(0, m.start() - 80) : m.end() + 80]
        ships = re.findall(r"(?:「|『|\{\{小图标\|)([^」』|\n]{2,16})", window)
        name = "限时建造" + (f"·{ships[0]}" if ships else "")
        out.append(
            {
                "name": name[:32],
                "label": "限时建造",
                "start": start,
                "end": end,
                "category": "gacha",
                "page": title,
            }
        )

    if out:
        banner = ""
        try:
            banner = page_banner(title)
        except Exception:
            banner = ""
        for e in out:
            e["banner"] = banner
    return out


def main() -> int:
    ref = now_cn()
    titles = list_rebuild_pages(ref.year)
    if ref.month <= 2:
        titles = list_rebuild_pages(ref.year - 1) + titles
    # 优先扫缓存齐全的近期页，减少无效请求
    recent = titles[-10:]
    print(f"  扫描 {len(recent)} 篇港区改建")

    collected: list[dict] = []
    for i, title in enumerate(recent):
        idx = titles.index(title) if title in titles else -1
        nxt = titles[idx + 1] if idx >= 0 and idx + 1 < len(titles) else None
        try:
            items = parse_page(title, nxt)
            print(f"  {title}: {len(items)}")
            collected.extend(items)
        except Exception as e:
            print(f"  [skip] {title}: {e}")
        time.sleep(0.7)

    best: dict[str, dict] = {}
    for e in collected:
        k = f"{e['name']}|{e['start'].date()}"
        prev = best.get(k)
        if not prev or e["end"] > prev["end"]:
            best[k] = e

    events = []
    for e in best.values():
        if e["end"] < ref:
            continue
        banner = ""
        if e.get("banner"):
            banner = cache_cover(f"al-{e['name'][:16]}", e["banner"], LINK_BASE)
        page_q = urllib.parse.quote(e["page"])
        stem = re.sub(r"[^\w\u4e00-\u9fff]+", "", e["name"])[:18]
        events.append(
            build_event(
                cid=f"al-{stem}-{e['start'].strftime('%m%d')}",
                title=e["name"],
                header=f"{e['label']}·{e['name']}"[:40],
                banner=banner,
                link=LINK_BASE + page_q,
                start=e["start"],
                end=e["end"],
                summary=e["page"],
                category=e["category"],
            )
        )

    events.sort(key=lambda x: (x["category"] != "combat", x.get("start") or ""))
    out_path = DATA / "azurlane.json"
    if not events and out_path.exists():
        try:
            prev = json.loads(out_path.read_text(encoding="utf-8"))
            if prev.get("events"):
                print("[azurlane] 本次抓取为空，保留上次数据（wiki 可能限流）")
                return 0
        except Exception:
            pass

    write_events(
        out_path,
        {
            "game": "碧蓝航线",
            "pending": False,
            "fetchedAt": ref.isoformat(),
            "count": len(events),
            "events": events,
            "source": "wiki.biligame.com/blhx 港区改建",
        },
    )
    print(f"[azurlane] {len(events)} 条进行中/预告")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
