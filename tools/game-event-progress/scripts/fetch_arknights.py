#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取明日方舟国服游戏内公告，解析活动起止时间，输出 data/events.json"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "events.json"
COVER_DIR = ROOT / "public" / "covers"
TZ = timezone(timedelta(hours=8))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ArknightsEventCal/1.0"

# 已知活动正确海报（避免误用通讯头图）
KNOWN_COVERS = {
    "红丝绒": "https://web.hycdn.cn/announce/images/20250526/da9b145d20fab5336b8afef11b4f8e48.jpg",
}

LIST_URL = "https://ak-webview.hypergryph.com/api/game/bulletinList?target=Android"
DETAIL_URL = "https://ak-webview.hypergryph.com/api/game/bulletin/{cid}"

# 公告正文里常见的时间写法
RANGE_PATTERNS = [
    # 07月10日 12:00 - 07月17日 03:59
    re.compile(
        r"(?P<label>[【\[]?[^：:\n]{0,20}?(?:时间|开放|开启|结束|截止)[^：:\n]{0,12})[：:]\s*"
        r"(?P<m1>\d{1,2})月(?P<d1>\d{1,2})日\s*(?P<h1>\d{1,2})[:：](?P<min1>\d{2})"
        r"\s*[-–—~至到]\s*"
        r"(?P<m2>\d{1,2})月(?P<d2>\d{1,2})日\s*(?P<h2>\d{1,2})[:：](?P<min2>\d{2})",
        re.I,
    ),
    # 2026年7月10日12:00 - 2026年7月24日03:59
    re.compile(
        r"(?P<label>[【\[]?[^：:\n]{0,20}?(?:时间|开放|开启|结束|截止)[^：:\n]{0,12})[：:]\s*"
        r"(?P<y1>20\d{2})年(?P<m1>\d{1,2})月(?P<d1>\d{1,2})日\s*(?P<h1>\d{1,2})[:：](?P<min1>\d{2})"
        r"\s*[-–—~至到]\s*"
        r"(?:(?P<y2>20\d{2})年)?(?P<m2>\d{1,2})月(?P<d2>\d{1,2})日\s*(?P<h2>\d{1,2})[:：](?P<min2>\d{2})",
        re.I,
    ),
    # 即日起至 / 活动结束时间：2026年7月31日23:59
    re.compile(
        r"活动结束时间[：:]\s*(?P<y2>20\d{2})年(?P<m2>\d{1,2})月(?P<d2>\d{1,2})日\s*(?P<h2>\d{1,2})[:：](?P<min2>\d{2})",
        re.I,
    ),
]

SKIP_TITLE = re.compile(r"封禁|停运|维护补偿|违规|账号|客服", re.I)

TYPE_RULES = [
    (re.compile(r"寻访|干员出率|卡池"), "寻访"),
    (re.compile(r"时装|新装|服饰|皮肤|复刻时装"), "时装"),
    (re.compile(r"故事集|活动即将|活动已|限时活动|作战|关卡|SideStory|危机合约"), "活动"),
    (re.compile(r"创作|征集|应援|衍生品|周边|官网"), "周边/社区"),
    (re.compile(r"维护|闪断|更新"), "维护"),
]

# 只要「需要打」的：有关卡时段，或故事集/作战类活动
SKIP_NOISE = re.compile(
    r"时装|新装|服饰|皮肤|衍生品|创作|征集|应援|官网|通讯|护航|账号|使用说明|家具|头像",
    re.I,
)

# 长公告里「【池名】限时寻访 … 活动时间：…」
GACHA_POOL_PAT = re.compile(
    r"[【\[](?P<name>[^】\]]{2,24})[】\]]\s*(?:限时)?寻访"
    r".{0,160}?"
    r"(?P<label>活动时间|寻访时间|开启时间)[：:\s]*"
    r"(?P<m1>\d{1,2})月(?P<d1>\d{1,2})日\s*(?P<h1>\d{1,2})[:：](?P<min1>\d{2})"
    r"\s*[-–—~至到]\s*"
    r"(?P<m2>\d{1,2})月(?P<d2>\d{1,2})日\s*(?P<h2>\d{1,2})[:：](?P<min2>\d{2})",
    re.S,
)

GACHA_TITLE_PAT = re.compile(r"寻访|干员出率|卡池")


def is_playable(title: str, header: str, text: str, ranges: list[dict[str, Any]], typ: str) -> bool:
    blob = f"{title} {header}"
    if typ == "寻访":
        return False
    if SKIP_NOISE.search(blob) and "关卡" not in text[:500]:
        # 标题本身是时装等，直接否
        if typ in ("时装", "周边/社区", "维护"):
            return False
    if any("关卡" in r.get("label", "") for r in ranges):
        return True
    if typ == "活动" and re.search(r"故事集|SideStory|危机合约|限时活动|活动即将|活动已开放", blob):
        return True
    if "关卡开放" in text or "活动关卡" in text:
        return True
    return False


def gacha_name_from_title(title: str) -> str:
    """从寻访公告标题提取池名。"""
    m = re.search(r"[【\[]([^】\]]{2,24})[】\]]", title)
    if m:
        return m.group(1).strip()
    t = re.sub(r"限时寻访开启|干员出率上升|限时出率上升|出率上升|限时寻访|寻访开启", "", title)
    t = re.sub(r"\s+", " ", t).strip(" ·-")
    return t or title


def parse_gacha_pools(text: str, ref: datetime) -> list[dict[str, Any]]:
    """从活动长公告抽取具名寻访卡池时段。"""
    pools: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in GACHA_POOL_PAT.finditer(text or ""):
        name = m.group("name").strip()
        if not name or name in seen:
            continue
        y1 = ref.year
        y2 = y1
        m1, d1 = int(m.group("m1")), int(m.group("d1"))
        m2, d2 = int(m.group("m2")), int(m.group("d2"))
        if (m2, d2) < (m1, d1):
            y2 += 1
        start = make_dt(y1, m1, d1, int(m.group("h1")), int(m.group("min1")))
        end = make_dt(y2, m2, d2, int(m.group("h2")), int(m.group("min2")))
        primary = {
            "label": f"{m.group('label')}·寻访",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "raw": re.sub(r"\s+", " ", m.group(0))[:160],
        }
        seen.add(name)
        pools.append({"name": name, "primary": primary})
    return pools


def gacha_fallback_range(display_time: str | None, updated: datetime | None, now: datetime) -> dict[str, Any]:
    """纯图寻访公告无展示日估时段（常见约两周）。"""
    start = None
    if display_time:
        try:
            y, mo, d = [int(x) for x in display_time.split("-")[:3]]
            # 限时寻访常见 12:00 / 16:00 开；估 16:00，后续可被长公告覆盖
            start = make_dt(y, mo, d, 16, 0)
        except Exception:
            start = None
    if start is None and updated:
        start = updated.replace(hour=16, minute=0, second=0, microsecond=0)
    if start is None:
        start = now.replace(hour=16, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=14)).replace(hour=3, minute=59, second=0, microsecond=0)
    return {
        "label": "估时（纯图公告）",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "raw": f"displayTime={display_time or '?'}",
    }


def http_get_json(url: str) -> dict[str, Any]:
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def safe_stem(name: str) -> str:
    """文件名只用 ASCII，避免 Windows 编码乱码。"""
    import hashlib

    ascii_part = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-")[:40]
    if not ascii_part or re.search(r"[\u4e00-\u9fff]", name):
        digest = hashlib.md5(name.encode("utf-8")).hexdigest()[:10]
        ascii_part = (ascii_part + "-" if ascii_part else "") + digest
    return ascii_part or "cover"


def cache_cover(cid: str, url: str) -> str:
    """把活动图下到 public/covers，避免外链防盗链导致页面空白。"""
    if not url:
        return ""
    COVER_DIR.mkdir(parents=True, exist_ok=True)
    ext = ".jpg"
    low = url.lower()
    if low.endswith(".png"):
        ext = ".png"
    elif low.endswith(".webp"):
        ext = ".webp"
    dest = COVER_DIR / f"{safe_stem(cid)}{ext}"
    # 已有且非空则复用
    if dest.exists() and dest.stat().st_size > 1000:
        return f"./covers/{dest.name}"
    try:
        req = Request(
            url,
            headers={
                "User-Agent": UA,
                "Referer": "https://ak.hypergryph.com/",
                "Accept": "image/*,*/*",
            },
        )
        with urlopen(req, timeout=40) as resp:
            data = resp.read()
        if len(data) < 500:
            return url
        dest.write_bytes(data)
        print(f"    [cover] {dest.name} ({len(data)} bytes)")
        return f"./covers/{dest.name}"
    except Exception as e:
        print(f"    [cover] 下载失败 {cid}: {e}")
        return url


def strip_html(html: str) -> str:
    text = unescape(html or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def clean_title(title: str) -> str:
    t = (title or "").replace("\\n", " ").replace("\n", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def guess_type(title: str, header: str, text: str) -> str:
    blob = f"{title} {header} {text[:200]}"
    for pat, name in TYPE_RULES:
        if pat.search(blob):
            return name
    return "其他"


def ts_to_dt(ts: int | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=TZ)


def make_dt(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


def parse_ranges(text: str, ref: datetime) -> list[dict[str, Any]]:
    """从公告正文抽出多段起止时间。"""
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for pat in RANGE_PATTERNS:
        for m in pat.finditer(text):
            g = m.groupdict()
            label = (g.get("label") or "活动时间").strip(" ：:")
            y1 = int(g["y1"]) if g.get("y1") else ref.year
            y2 = int(g["y2"]) if g.get("y2") else y1

            # 只有结束时间的「即日起～截止」
            if g.get("m1") is None and g.get("m2"):
                end = make_dt(y2, int(g["m2"]), int(g["d2"]), int(g["h2"]), int(g["min2"]))
                start = ref
                key = (start.isoformat(), end.isoformat())
                if key in seen:
                    continue
                seen.add(key)
                found.append(
                    {
                        "label": label or "活动截止",
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "raw": m.group(0)[:120],
                    }
                )
                continue

            m1, d1 = int(g["m1"]), int(g["d1"])
            m2, d2 = int(g["m2"]), int(g["d2"])
            h1, min1 = int(g["h1"]), int(g["min1"])
            h2, min2 = int(g["h2"]), int(g["min2"])

            # 跨年：结束月 < 开始月
            if y2 == y1 and (m2, d2) < (m1, d1):
                y2 += 1

            start = make_dt(y1, m1, d1, h1, min1)
            end = make_dt(y2, m2, d2, h2, min2)
            key = (start.isoformat(), end.isoformat())
            if key in seen:
                continue
            seen.add(key)
            found.append(
                {
                    "label": label,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "raw": m.group(0)[:120],
                }
            )

    # 无标签的裸时间段：07月10日 12:00 - 07月17日 03:59
    bare = re.compile(
        r"(?P<m1>\d{1,2})月(?P<d1>\d{1,2})日\s*(?P<h1>\d{1,2})[:：](?P<min1>\d{2})"
        r"\s*[-–—~至到]\s*"
        r"(?P<m2>\d{1,2})月(?P<d2>\d{1,2})日\s*(?P<h2>\d{1,2})[:：](?P<min2>\d{2})"
    )
    for m in bare.finditer(text):
        g = m.groupdict()
        y1 = ref.year
        y2 = y1
        m1, d1 = int(g["m1"]), int(g["d1"])
        m2, d2 = int(g["m2"]), int(g["d2"])
        if (m2, d2) < (m1, d1):
            y2 += 1
        start = make_dt(y1, m1, d1, int(g["h1"]), int(g["min1"]))
        end = make_dt(y2, m2, d2, int(g["h2"]), int(g["min2"]))
        key = (start.isoformat(), end.isoformat())
        if key in seen:
            continue
        # 避免把无关短句全吃进来：时长 1 小时～90 天
        hours = (end - start).total_seconds() / 3600
        if hours < 1 or hours > 24 * 90:
            continue
        seen.add(key)
        found.append(
            {
                "label": "时段",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "raw": m.group(0),
            }
        )

    return found


def pick_primary(ranges: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not ranges:
        return None
    # 优先「活动时间 / 关卡开放 / 寻访」
    prefer = ("活动时间", "关卡开放", "开放时间", "寻访", "开启")
    for p in prefer:
        for r in ranges:
            if p in r["label"]:
                return r
    # 否则取跨度最长的一段（主活动）
    return max(
        ranges,
        key=lambda r: (
            datetime.fromisoformat(r["end"]) - datetime.fromisoformat(r["start"])
        ).total_seconds(),
    )


def status_of(start: datetime | None, end: datetime | None, now: datetime) -> str:
    if start and end:
        if now < start:
            return "即将开始"
        if now > end:
            return "已结束"
        return "进行中"
    if end and now > end:
        return "已结束"
    if start and now < start:
        return "即将开始"
    return "进行中"


def remain_text(start: datetime | None, end: datetime | None, now: datetime) -> str:
    if start and now < start:
        d = start - now
        days = d.days
        hours = d.seconds // 3600
        if days > 0:
            return f"{days}天后"
        if hours > 0:
            return f"{hours}小时后"
        return "即将开始"
    if end:
        if now > end:
            return "已结束"
        d = end - now
        days = d.days
        hours = d.seconds // 3600
        mins = (d.seconds % 3600) // 60
        if days > 0:
            return f"剩{days}天{hours}时" if hours else f"剩{days}天"
        if hours > 0:
            return f"剩{hours}小时"
        return f"剩{mins}分"
    return "时间未知"


def progress_pct(start: datetime | None, end: datetime | None, now: datetime) -> float:
    """时间进度：从开始到结束已过去的比例（0~100）。"""
    if not start or not end or end <= start:
        return 0.0
    if now <= start:
        return 0.0
    if now >= end:
        return 100.0
    return round(100.0 * (now - start).total_seconds() / (end - start).total_seconds(), 1)


def day_span(start: datetime | None, end: datetime | None, now: datetime) -> dict[str, Any]:
    """给人看的天数：已过 / 剩余 / 总长（按自然小时折算到天，保留1位）。"""
    if not start or not end or end <= start:
        return {"elapsedDays": 0, "remainDays": 0, "totalDays": 0}
    total_h = (end - start).total_seconds() / 3600
    total_d = round(total_h / 24, 1)
    if now <= start:
        return {
            "elapsedDays": 0,
            "remainDays": round((start - now).total_seconds() / 86400, 1),
            "totalDays": total_d,
            "untilStartDays": round((start - now).total_seconds() / 86400, 1),
        }
    if now >= end:
        return {"elapsedDays": total_d, "remainDays": 0, "totalDays": total_d}
    elapsed_d = round((now - start).total_seconds() / 86400, 1)
    remain_d = round((end - now).total_seconds() / 86400, 1)
    return {"elapsedDays": elapsed_d, "remainDays": remain_d, "totalDays": total_d}


def pick_banner(detail: dict[str, Any], html: str) -> str:
    """挑活动海报：优先正文第一张（常为活动头图），避开时装/礼包图。"""
    official = (detail.get("bannerImageUrl") or "").strip()
    html = html or ""
    imgs = re.findall(
        r'src="(https://web\.hycdn\.cn/announce/images/[^"]+\.(?:png|jpg|jpeg|webp))"',
        html,
        flags=re.I,
    )
    seen: list[str] = []
    for u in imgs:
        if u not in seen:
            seen.append(u)

    bad = re.compile(r"售卖|时装|新装|源石|礼包|采购凭证|干员寻访|服饰")

    def score(url: str) -> tuple[int, int]:
        idx = html.find(url)
        ctx = html[max(0, idx - 160) : idx + 80]
        if bad.search(ctx):
            return (9, idx)
        # 正文越靠前越好（活动头图通常第一张）
        return (0, idx)

    if seen:
        ranked = sorted(seen, key=score)
        best = ranked[0]
        if score(best)[0] == 0:
            return best
    return official or (seen[0] if seen else "")


def fetch_all() -> dict[str, Any]:
    now = datetime.now(TZ)
    print(f"[fetch] 列表 {LIST_URL}")
    listing = http_get_json(LIST_URL)
    items = listing.get("data", {}).get("list") or []
    print(f"[fetch] 共 {len(items)} 条公告")

    events: list[dict[str, Any]] = []
    notes: list[str] = []
    # 关键词 -> 可用时段（来自长公告），供图片公告借用
    keyword_ranges: dict[str, list[dict[str, Any]]] = {}
    # 具名寻访时段（从活动长公告抽取）
    gacha_pool_times: dict[str, dict[str, Any]] = {}
    # 纯图寻访海报，等时段齐了再出卡
    pending_gacha: list[dict[str, Any]] = []

    def theme_keys(*parts: str) -> list[str]:
        blob = " ".join(parts)
        keys = re.findall(r"[「【]([^」】]{2,16})[」】]", blob)
        # 再捞常见活动名片段
        for m in re.finditer(
            r"(丛林症结|确定性混沌|小马宝莉|音律联觉|珊瑚海岸|命途迭代|中坚寻访|常驻标准寻访|永不落幕)",
            blob,
        ):
            keys.append(m.group(1))
        # 去重保序
        out: list[str] = []
        for k in keys:
            if k not in out:
                out.append(k)
        return out

    def enrich(ev: dict[str, Any], start: datetime | None, end: datetime | None) -> dict[str, Any]:
        ev["start"] = start.isoformat() if start else None
        ev["end"] = end.isoformat() if end else None
        ev["status"] = status_of(start, end, now)
        ev["remain"] = remain_text(start, end, now)
        ev["progress"] = progress_pct(start, end, now)
        ev["days"] = day_span(start, end, now)
        ev["hasSchedule"] = bool(start and end)
        ev["kind"] = (
            "preview"
            if ev["status"] == "即将开始"
            else ("done" if ev["status"] == "已结束" else "live")
        )
        return ev

    def build_event(
        *,
        cid: str,
        title: str,
        header: str,
        banner: str,
        jump: str,
        updated: datetime | None,
        text: str,
        ranges: list[dict[str, Any]],
        primary: dict[str, Any] | None,
        suffix: str = "",
    ) -> dict[str, Any]:
        start = datetime.fromisoformat(primary["start"]) if primary else None
        end = datetime.fromisoformat(primary["end"]) if primary else None
        show_title = f"{title}{suffix}" if suffix else title
        if suffix:
            safe = re.sub(r"\W+", "", suffix)[:12]
            sid = f"{cid}-{safe}"
        else:
            sid = cid
        return enrich(
            {
                "id": sid,
                "title": show_title,
                "header": header,
                "type": guess_type(show_title, header, text),
                "banner": banner,
                "link": jump or "https://ak.hypergryph.com/",
                "updatedAt": updated.isoformat() if updated else None,
                "primaryLabel": primary["label"] if primary else None,
                "allRanges": ranges,
                "summary": "",
                "textPreview": (text or "").strip()[:1600],
            },
            start,
            end,
        )

    for i, meta in enumerate(items, 1):
        cid = str(meta.get("cid") or "")
        title = clean_title(meta.get("title") or "")
        if not cid or SKIP_TITLE.search(title):
            continue
        # 过滤无关；制作组通讯单独只挖「未来关卡预告」；寻访/卡池保留
        is_newsletter = bool(re.search(r"制作组通讯", title))
        is_gacha_post = bool(GACHA_TITLE_PAT.search(title))
        if (
            re.search(
                r"护航指引|双平台账号|使用说明|罗德岛通讯|"
                r"时装|新装|服饰|衍生品|创作征集|创作者应援|"
                r"限时上架|限时复刻上架|回顾展|联动系列",
                title,
            )
            and not is_newsletter
            and not is_gacha_post
        ):
            continue

        print(f"  [{i}/{len(items)}] {cid} {title}")
        try:
            detail = http_get_json(DETAIL_URL.format(cid=cid)).get("data") or {}
        except Exception as e:
            notes.append(f"{cid} 详情失败: {e}")
            continue

        header = clean_title(detail.get("header") or "")
        html = detail.get("content") or ""
        text = strip_html(html)
        banner = pick_banner(detail, html)
        # 寻访纯图公告：bannerImageUrl 即卡池海报
        if is_gacha_post and detail.get("bannerImageUrl"):
            banner = detail.get("bannerImageUrl") or banner
        jump = detail.get("jumpLink") or ""
        updated = ts_to_dt(detail.get("updatedAt") or meta.get("updatedAt"))
        ref = updated or now
        display_time = detail.get("displayTime") or meta.get("displayTime")

        ranges = parse_ranges(text, ref)
        keys = theme_keys(title, header, text[:400])
        for k in keys:
            keyword_ranges.setdefault(k, []).extend(ranges)

        # 长公告里的具名寻访 → 供纯图卡池公告对齐时段
        for pool in parse_gacha_pools(text, ref):
            gacha_pool_times[pool["name"]] = pool["primary"]
            keyword_ranges.setdefault(pool["name"], []).append(pool["primary"])
            notes.append(f"{cid} 解析寻访「{pool['name']}」时段")

        if is_gacha_post:
            pending_gacha.append(
                {
                    "cid": cid,
                    "title": title,
                    "name": gacha_name_from_title(title),
                    "banner": banner,
                    "jump": jump,
                    "updated": updated,
                    "displayTime": display_time,
                    "text": text,
                }
            )
            continue

        # 通讯：精确时段 + 「X月上/中/下旬」模糊预告
        if is_newsletter:
            for ri, r in enumerate(ranges):
                st = datetime.fromisoformat(r["start"])
                if st <= now:
                    continue
                if not re.search(r"关卡|活动|开放|开启", r["label"]):
                    continue
                name_m = re.search(
                    r"[「【]([^」】]{2,20})[」】].{0,40}" + re.escape(r["raw"][:20]),
                    text,
                )
                pname = name_m.group(1) if name_m else r["label"]
                pev = build_event(
                    cid=f"{cid}-p{ri}",
                    title=f"预告·{pname}",
                    header=f"「{pname}」即将开启",
                    banner=banner,
                    jump=jump,
                    updated=updated,
                    text=text,
                    ranges=[r],
                    primary=r,
                )
                pev["playable"] = True
                pev["type"] = "活动"
                pev["category"] = "combat"
                pev["kind"] = "preview"
                pev["fuzzy"] = False
                events.append(pev)
                notes.append(f"{cid} 通讯预告：{pname}")

            # 模糊预告：将于7月下旬开启 / SideStory「丝垢」复刻…
            # 用「时段起点」估算：上旬1日、中旬11日、下旬21日
            # 中下旬≈21日，上中旬≈8日
            part_day = {
                "上旬": 1,
                "上中旬": 8,
                "中旬": 11,
                "中下旬": 21,
                "下旬": 21,
                "月初": 1,
                "月底": 25,
            }
            part_alt = "上中旬|中下旬|上旬|中旬|下旬|月初|月底"
            patterns = [
                re.compile(
                    rf"SideStory\s*[「【](?P<name>[^」】]{{2,20}})[」】]"
                    rf"[^。]{{0,80}}?(?P<m>\d{{1,2}})月(?P<part>{part_alt})",
                    re.I,
                ),
                re.compile(
                    rf"[「【](?P<name>[^」】]{{2,20}})[」】]"
                    rf"[^。]{{0,50}}?(?:限时)?(?:活动|复刻|作战)[^。]{{0,40}}?"
                    rf"(?P<m>\d{{1,2}})月(?P<part>{part_alt})"
                ),
            ]
            deny_name = re.compile(r"时装|家具|头像|寻访|源石|通讯|清单|演算|矩阵|集成战略")
            seen_names: set[str] = set()
            notes.append(f"{cid} 通讯正文 {len(text)} 字")
            fi = 0
            for pat in patterns:
                for m in pat.finditer(text):
                    pname = m.group("name").strip()
                    if not pname or pname in seen_names or deny_name.search(pname):
                        continue
                    seen_names.add(pname)
                    mo = int(m.group("m"))
                    day = part_day[m.group("part")]
                    start = make_dt(now.year, mo, day, 16, 0)
                    if (start.month, start.day) < (now.month - 2, now.day):
                        start = make_dt(now.year + 1, mo, day, 16, 0)
                    if start <= now:
                        notes.append(
                            f"{cid} 预告已过期：{pname} {mo}月{m.group('part')}"
                        )
                        continue
                    end = start + timedelta(days=8)
                    primary = {
                        "label": f"{mo}月{m.group('part')}（估）",
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "raw": m.group(0)[:120],
                    }
                    prefer = KNOWN_COVERS.get(pname) or banner
                    cover = cache_cover(f"event-{safe_stem(pname)}", prefer) if prefer else ""
                    pev = build_event(
                        cid=f"{cid}-f{fi}",
                        title=f"预告·{pname}",
                        header=f"「{pname}」预计{mo}月{m.group('part')}开启",
                        banner=cover or prefer or banner,
                        jump=jump,
                        updated=updated,
                        text=text,
                        ranges=[primary],
                        primary=primary,
                    )
                    pev["playable"] = True
                    pev["type"] = "活动"
                    pev["category"] = "combat"
                    pev["kind"] = "preview"
                    pev["fuzzy"] = True
                    events.append(pev)
                    notes.append(
                        f"{cid} 模糊预告：{pname} {mo}月{m.group('part')}"
                    )
                    fi += 1
            continue

        stage = next((r for r in ranges if "关卡" in r["label"]), None)
        primary = stage or pick_primary(ranges)
        typ = guess_type(title, header, text)
        blob = f"{title} {header}"
        if re.search(r"寻访|卡池|干员出率", blob):
            category = "gacha"
        elif is_playable(title, header, text, ranges, typ):
            category = "combat"
        elif re.search(r"时装|签到|兑换|维护|创作|征集", blob):
            category = "event"
            if not ranges:
                notes.append(f"{cid} 跳过无时段：{title}")
                continue
        else:
            notes.append(f"{cid} 跳过：{title}")
            continue

        local_banner = cache_cover(cid, banner) if banner else ""
        ev = build_event(
            cid=cid,
            title=title,
            header=header,
            banner=local_banner or banner,
            jump=jump,
            updated=updated,
            text=text,
            ranges=ranges,
            primary=primary,
        )
        ev["bannerRemote"] = banner
        ev["playable"] = category == "combat"
        ev["category"] = category
        ev["type"] = typ or "活动"
        events.append(ev)
        if stage:
            notes.append(f"{cid} 采用关卡开放时间")

        # 同一公告里若还有更晚的关卡时段，额外出预告卡
        for ri, r in enumerate(ranges):
            if "关卡" not in r["label"]:
                continue
            if primary and r["start"] == primary["start"] and r["end"] == primary["end"]:
                continue
            st = datetime.fromisoformat(r["start"])
            if st <= now:
                continue
            pev = build_event(
                cid=f"{cid}-next{ri}",
                title=f"{title}·后续",
                header=header or title,
                banner=local_banner or banner,
                jump=jump,
                updated=updated,
                text=text,
                ranges=[r],
                primary=r,
            )
            pev["playable"] = True
            pev["type"] = "活动"
            pev["kind"] = "preview"
            events.append(pev)

    # 寻访/卡池：专用海报公告 + 长公告时段对齐
    emitted_gacha: set[str] = set()
    for g in pending_gacha:
        name = g["name"]
        primary = gacha_pool_times.get(name)
        fuzzy = False
        if not primary:
            # 宽松匹配：池名互相包含
            for k, pr in gacha_pool_times.items():
                if name in k or k in name:
                    primary = pr
                    break
        if not primary:
            for k in theme_keys(g["title"], name):
                cands = keyword_ranges.get(k) or []
                hit = next(
                    (r for r in cands if re.search(r"寻访|活动时间", r.get("label", ""))),
                    None,
                )
                if hit:
                    primary = hit
                    break
        if not primary:
            primary = gacha_fallback_range(g.get("displayTime"), g.get("updated"), now)
            fuzzy = True
            notes.append(f"{g['cid']} 寻访「{name}」用展示日估时")
        else:
            notes.append(f"{g['cid']} 寻访「{name}」对齐长公告时段")

        local_banner = cache_cover(f"gacha-{g['cid']}", g["banner"]) if g["banner"] else ""
        gev = build_event(
            cid=g["cid"],
            title=g["title"],
            header=f"「{name}」限时寻访",
            banner=local_banner or g["banner"],
            jump=g["jump"] or "https://ak.hypergryph.com/",
            updated=g["updated"],
            text=g.get("text") or "",
            ranges=[primary],
            primary=primary,
        )
        gev["bannerRemote"] = g["banner"]
        gev["playable"] = False
        gev["category"] = "gacha"
        gev["type"] = "寻访"
        gev["fuzzy"] = fuzzy
        gev["summary"] = f"卡池「{name}」"
        events.append(gev)
        emitted_gacha.add(name)

    # 长公告里有寻访时段、但没有对应海报公告时，也出一张卡池卡
    for name, primary in gacha_pool_times.items():
        if name in emitted_gacha:
            continue
        if any(e.get("category") == "gacha" and name in (e.get("header") or e.get("title") or "") for e in events):
            continue
        end = datetime.fromisoformat(primary["end"])
        if end < now - timedelta(days=1):
            continue
        gev = build_event(
            cid=f"gacha-{safe_stem(name)}",
            title=f"【{name}】限时寻访",
            header=f"「{name}」限时寻访",
            banner="",
            jump="https://ak.hypergryph.com/",
            updated=now,
            text="",
            ranges=[primary],
            primary=primary,
        )
        gev["playable"] = False
        gev["category"] = "gacha"
        gev["type"] = "寻访"
        gev["summary"] = f"卡池「{name}」"
        events.append(gev)
        notes.append(f"补全寻访卡「{name}」（无独立海报公告）")

    # 二次：作战活动缺时间时，借用同关键词里的「关卡开放」
    for e in events:
        if e["hasSchedule"]:
            continue
        keys = theme_keys(e["title"], e["header"])
        donor_ranges: list[dict[str, Any]] = []
        donor_key = ""
        for k in keys:
            if keyword_ranges.get(k):
                donor_ranges = keyword_ranges[k]
                donor_key = k
                break
        if not donor_ranges:
            continue
        prefer_lab = "寻访" if e.get("category") == "gacha" else "关卡"
        primary = next((r for r in donor_ranges if prefer_lab in r["label"]), None) or pick_primary(
            donor_ranges
        )
        if not primary:
            continue
        start = datetime.fromisoformat(primary["start"])
        end = datetime.fromisoformat(primary["end"])
        enrich(e, start, end)
        e["primaryLabel"] = f"推断自「{donor_key}」·{primary['label']}"
        e["allRanges"] = [primary]
        notes.append(f"{e['id']} 时间由关键词「{donor_key}」推断")

    # 去重：同 title+start+end；模糊预告若已有同名精确进行中则丢掉
    def core_name(e: dict[str, Any]) -> str:
        blob = e.get("header") or e.get("title") or ""
        m = re.search(r"[「【]([^」】]+)[」】]", blob)
        return (m.group(1) if m else blob).replace("预告·", "").strip()

    live_names = {
        core_name(e)
        for e in events
        if e.get("status") == "进行中" and not e.get("fuzzy")
    }
    uniq: list[dict[str, Any]] = []
    seen_u: set[tuple[str, str | None, str | None]] = set()
    for e in events:
        key = (e["title"], e.get("start"), e.get("end"))
        if key in seen_u:
            continue
        if e.get("fuzzy") and core_name(e) in live_names:
            continue
        seen_u.add(key)
        uniq.append(e)
    events = uniq

    # 排序：进行中 > 即将开始 > 已结束/未知；同组按结束时间
    order = {"进行中": 0, "即将开始": 1, "已结束": 2}

    def sort_key(e: dict[str, Any]):
        return (
            0 if e["hasSchedule"] else 1,
            order.get(e["status"], 9),
            e.get("end") or "9999",
        )

    events.sort(key=sort_key)

    payload = {
        "game": "明日方舟",
        "source": LIST_URL,
        "fetchedAt": now.isoformat(),
        "timezone": "Asia/Shanghai",
        "count": len(events),
        "notes": notes,
        "analysis": {
            "method": "官方游戏内公告 API + 正则抽取活动时间段",
            "detailApi": DETAIL_URL,
            "tips": [
                "长公告（如「活动即将开启」）常含多段时间：关卡/兑换/寻访分别解析",
                "寻访纯图公告用海报；时段优先对齐活动长公告里的「【池名】限时寻访」",
                "中坚/标准等无展示日估时（约两周），有长公告则覆盖",
                "进度条按主时段（优先「活动时间/关卡开放/寻访」）计算已过比例",
            ],
        },
        "events": events,
    }
    return payload


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = fetch_all()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] 写入 {OUT} （{data['count']} 条）")
    scheduled = sum(1 for e in data["events"] if e["hasSchedule"])
    print(f"[ok] 解析到时间表 {scheduled}/{data['count']}")
    for e in data["events"][:8]:
        print(
            f"  - [{e['status']}] {e['title']} | {e['remain']} | "
            f"{(e['start'] or '?')[:16]} → {(e['end'] or '?')[:16]}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
