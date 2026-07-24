#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取鸣潮国服官网版本说明 / 活动公告。"""

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
    http_get_json,
    make_dt,
    now_cn,
    strip_html,
    write_events,
)
from urllib.parse import urlencode, urljoin


def abs_url(url: str, base: str = "") -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("http"):
        return u
    return urljoin(base, u) if base else u

UA = {
    "User-Agent": "Mozilla/5.0 GameEventCal/1.1",
    "Accept": "*/*",
    "Referer": "https://wutheringwaves.kurogames.com/",
}
BASE = "https://media-cdn-mingchao.kurogame.com/akiwebsite/website2.0/json/G152/zh/"
LINK = "https://wutheringwaves.kurogames.com/zh/main/news"

# kind 只吃短类型词，避免把正文说明吞进标题
KIND = (
    r"(?P<kind>危机情景挑战活动|战斗拍照活动|限时委托活动|角色活动唤取|武器活动唤取|"
    r"七日签到活动|网页活动|战斗活动|挑战活动|委托活动|拍照活动|签到活动|限时活动)"
)

# [悲鸣行动：无音危机]战斗活动 …… ✦活动时间：…
BLOCK = re.compile(
    rf"\[(?P<name>[^\]]{{2,40}})\]{KIND}"
    r"(?P<ctx>[^\[]{0,260}?)"
    r"(?P<label>活动时间|开放时间)\s*[：:]\s*"
    r"(?P<body>"
    r"(?:(?P<ver>\d+\.\d+版本更新后)\s*[~～\-–—至到]\s*)?"
    r"(?:(?P<y1>20\d{2})年)?(?P<m1>\d{1,2})月(?P<d1>\d{1,2})日\s*(?P<h1>\d{1,2})[:：](?P<min1>\d{2})"
    r"\s*[~～\-–—至到]\s*"
    r"(?:(?P<y2>20\d{2})年)?(?P<m2>\d{1,2})月(?P<d2>\d{1,2})日\s*(?P<h2>\d{1,2})[:：](?P<min2>\d{2})"
    r")",
)

# 「秘玉寻踪记」网页活动
QUOTE_BLOCK = re.compile(
    rf"「(?P<name>[^」]{{2,30}})」{KIND}"
    r"(?P<ctx>[^「]{0,160}?)"
    r"(?P<label>活动时间|开放时间)\s*[：:]\s*"
    r"(?P<body>"
    r"(?:(?P<y1>20\d{2})年)?(?P<m1>\d{1,2})月(?P<d1>\d{1,2})日\s*(?P<h1>\d{1,2})[:：](?P<min1>\d{2})"
    r"\s*[~～\-–—至到]\s*"
    r"(?:(?P<y2>20\d{2})年)?(?P<m2>\d{1,2})月(?P<d2>\d{1,2})日\s*(?P<h2>\d{1,2})[:：](?P<min2>\d{2})"
    r")",
)

GACHA_NAME = re.compile(
    r"\[(?P<a>[^\]]{2,30})\]角色活动唤取|"
    r"[「【](?P<b>[^」】]{2,30})[」】]武器活动唤取"
)

# 正文顺序：5星共鸣者「角色」…可通过[池名]角色活动唤取
GACHA_SUBJECT = re.compile(
    r"(?:5星共鸣者|共鸣者)[「【](?P<sub>[^」】]{2,24})[」】]"
    r".{0,240}?"
    r"可通过\[(?P<pool>[^\]]{2,40})\]角色活动唤取",
    re.S,
)
# 5星武器「名」…可通过「名」武器活动唤取
WEAPON_SUBJECT = re.compile(
    r"5星武器[「【](?P<sub>[^」】]{2,24})[」】]"
    r".{0,200}?"
    r"可通过[「【](?P=sub)[」】]武器活动唤取",
    re.S,
)

SKIP_KIND = re.compile(r"永久|商城|服饰|优化|修复")
FANDOM_ZH = "https://wutheringwaves.fandom.com/zh/api.php"


def parse_dt(y: int | None, m: str, d: str, h: str, mi: str, fallback_year: int) -> datetime:
    return make_dt(int(y or fallback_year), int(m), int(d), int(h), int(mi))


def wuwa_category(name: str, kind: str) -> str:
    blob = f"{name} {kind}"
    if re.search(r"网页|H5|专题", blob):
        return "web"
    if re.search(r"唤取|调谐|武器活动", blob):
        return "gacha"
    if re.search(r"签到|登录|委托|拍照|留影|探索|赠礼|邮币|收集", blob):
        return "event"
    if re.search(r"战斗|挑战|危机|演习|作战|无音|终焉|矩阵|虚域|危情", blob):
        return "combat"
    return "event"


def first_image(html: str) -> str:
    imgs = re.findall(
        r'(?:src|data-src)=["\'](https?://[^"\']+\.(?:jpg|jpeg|png|webp)[^"\']*)["\']',
        html or "",
        re.I,
    )
    return imgs[0] if imgs else ""


def fandom_imageinfo(titles: list[str]) -> dict[str, str]:
    """File:xxx → url"""
    if not titles:
        return {}
    out: dict[str, str] = {}
    for i in range(0, len(titles), 40):
        chunk = titles[i : i + 40]
        try:
            data = http_get_json(
                FANDOM_ZH
                + "?"
                + urlencode(
                    {
                        "action": "query",
                        "titles": "|".join(chunk),
                        "prop": "imageinfo",
                        "iiprop": "url",
                        "format": "json",
                    }
                ),
                {"User-Agent": UA["User-Agent"], "Accept": "application/json"},
            )
        except Exception:
            continue
        for page in (data.get("query") or {}).get("pages", {}).values():
            title = page.get("title") or ""
            infos = page.get("imageinfo") or []
            if infos and infos[0].get("url"):
                out[title] = infos[0]["url"]
    return out


def fandom_pageimage(title: str) -> str:
    try:
        data = http_get_json(
            FANDOM_ZH
            + "?"
            + urlencode(
                {
                    "action": "query",
                    "titles": title,
                    "prop": "pageimages",
                    "pithumbsize": 800,
                    "redirects": 1,
                    "format": "json",
                }
            ),
            {"User-Agent": UA["User-Agent"], "Accept": "application/json"},
        )
    except Exception:
        return ""
    for page in (data.get("query") or {}).get("pages", {}).values():
        thumb = page.get("thumbnail") or {}
        if thumb.get("source"):
            return thumb["source"]
    return ""


def norm_name(s: str) -> str:
    return (
        (s or "")
        .replace("・", "·")
        .replace("‧", "·")
        .replace("：", ":")
        .strip()
    )


def fandom_subject_cover(subject: str) -> str:
    """优先唤取立绘，其次角色形象/立绘。"""
    subject = norm_name(subject)
    if not subject:
        return ""
    variants = [subject]
    if "·" in subject:
        variants.append(subject.split("·")[0])  # 秧秧·玄翎 → 秧秧
    suffixes = ["唤取立绘.png", "角色形象.jpg", "角色形象.png", "全身照.png", "立绘.png"]
    candidates = [f"File:{v} {suf}" for v in variants for suf in suffixes]
    found = fandom_imageinfo(candidates)
    for v in variants:
        for key in ("唤取立绘", "角色形象", "全身照", "立绘"):
            for k, u in found.items():
                kn = k.replace("_", " ")
                if v in kn and key in kn:
                    return u
    if found:
        return next(iter(found.values()))
    for v in variants:
        img = fandom_pageimage(v)
        if img:
            return img
    return ""


CHAR_MENTION = re.compile(r"(?:5星共鸣者|共鸣者)[「【](?P<sub>[^」】]{2,24})[」】]")
WEAPON_MENTION = re.compile(r"5星武器[「【](?P<wep>[^」】]{2,24})[」】]")


def extract_subjects(text: str) -> dict[str, str]:
    """活动/卡池名 → 关联角色名（武器池挂到对应角色图）。"""
    out: dict[str, str] = {}
    for m in GACHA_SUBJECT.finditer(text):
        pool = (m.group("pool") or "").strip()
        sub = (m.group("sub") or "").strip()
        if pool and sub and "漂泊者" not in sub:
            out[pool] = sub
    chars = [
        m.group("sub").strip()
        for m in CHAR_MENTION.finditer(text)
        if m.group("sub") and "漂泊者" not in m.group("sub")
    ]
    # 去重保序（正文可能重复提及）
    char_order: list[str] = []
    for c in chars:
        if c not in char_order:
            char_order.append(c)
    weapons = [
        m.group("wep").strip()
        for m in WEAPON_MENTION.finditer(text)
        if m.group("wep")
    ]
    wep_order: list[str] = []
    for w in weapons:
        if w not in wep_order:
            wep_order.append(w)
    # 专武与角色按出现顺序一一对应
    for i, wep in enumerate(wep_order):
        if i < len(char_order):
            out[wep] = char_order[i]
        elif wep not in out:
            out[wep] = wep
    return out


def cover_referer(url: str) -> str:
    if "wikia" in url or "fandom" in url:
        return "https://wutheringwaves.fandom.com/"
    if "gamekee" in url:
        return "https://www.gamekee.com/"
    return LINK


def load_gamekee_covers() -> list[tuple[str, str]]:
    """[(title, pic_url), ...] GameKee 鸣潮日历，供系列活动配图。"""
    try:
        raw = http_get_json(
            "https://www.gamekee.com/v1/activity/page-list"
            "?importance=0&sort=-1&keyword=&limit=80&page_no=1&status=0",
            {
                "game-alias": "mc",
                "Referer": "https://www.gamekee.com/mc/",
                "Accept": "application/json",
                "User-Agent": UA["User-Agent"],
            },
        )
    except Exception:
        return []
    rows = raw.get("data") or []
    if isinstance(rows, dict):
        rows = rows.get("list") or []
    out: list[tuple[str, str]] = []
    for it in rows:
        title = (it.get("title") or "").strip()
        pic = abs_url(
            it.get("big_picture") or it.get("picture") or "",
            "https://cdnimg-v2.gamekee.com/",
        )
        if title and pic:
            out.append((title, pic))
    return out


def gamekee_match(name: str, rows: list[tuple[str, str]], category: str = "") -> str:
    if not name or not rows:
        return ""
    # 精确包含
    for title, pic in rows:
        if name in title or title in name:
            return pic
    # 系列片段：虚域危局 / 呜呜企划 / 光影瞬息（再续・光影瞬息）
    parts = [p.strip() for p in re.split(r"[：:・·]", name) if p and len(p.strip()) >= 3]
    for stem in [name, *parts]:
        for title, pic in rows:
            if stem in title:
                return pic
    # 网页活动：用日历里任意网页活动图（总比空白好，且通常是 H5 海报）
    if category == "web":
        for title, pic in rows:
            if "网页" in title:
                return pic
    return ""


def menu_dedicated_cover(menu: list[dict], name: str) -> str:
    """官网独立活动公告（非版本说明）的首图。"""
    stem = re.split(r"[：:・·]", name, maxsplit=1)[0].strip()
    hits = []
    for a in menu:
        title = a.get("articleTitle") or ""
        if "内容说明" in title or "维护预告" in title or "概率公示" in title:
            continue
        if name in title or (stem and stem in title) or (len(name) >= 4 and name[:4] in title):
            hits.append(a)
    hits.sort(key=lambda a: a.get("startTime") or a.get("createTime") or "", reverse=True)
    for a in hits[:5]:
        try:
            detail = http_get_json(BASE + f"article/{a['articleId']}.json", UA)
        except Exception:
            continue
        if not isinstance(detail, dict):
            continue
        img = first_image(detail.get("articleContent") or "") or (detail.get("suggestCover") or "")
        if img:
            return img
    return ""


def resolve_banner(
    *,
    name: str,
    category: str,
    subjects: dict[str, str],
    menu: list[dict],
    gk_rows: list[tuple[str, str]],
    version_banner: str = "",
) -> str:
    # 1) 独立公告（含往期同系列预告图）
    img = menu_dedicated_cover(menu, name)
    if img:
        return img
    # 2) 卡池：角色/武器立绘
    sub = subjects.get(name)
    if not sub and category == "gacha":
        sub = name
    if sub:
        img = fandom_subject_cover(sub)
        if img:
            return img
    # 3) GameKee 同名/系列活动图
    img = gamekee_match(name, gk_rows, category)
    if img:
        return img
    # 4) 作战主活动：版本 KV 兜底（只给 combat，避免所有卡同一张）
    if category == "combat" and version_banner:
        return version_banner
    # 5) 拍照/系列活动：GameKee 系列图；不用版本 KV（避免和主作战同图）
    if category == "event" and ("光影" in name or "瞬息" in name or "拍照" in name):
        for title, pic in gk_rows:
            if "光影" in title or "瞬息" in title or "拍照" in title or "留影" in title:
                return pic
        img = fandom_pageimage("光影瞬息") or fandom_pageimage("战斗拍照")
        if img:
            return img
    return ""


def extract_maint_start(text: str, ref: datetime) -> datetime | None:
    m = re.search(
        r"更新维护时间[：:]\s*20(\d{2})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2})[:：](\d{2})",
        text,
    )
    if not m:
        return None
    return make_dt(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)))


def ranges_from_match(m: re.Match, maint: datetime | None, ref: datetime) -> tuple[datetime, datetime] | None:
    g = m.groupdict()
    y_fallback = ref.year
    if g.get("ver") and maint:
        start = maint
    else:
        start = parse_dt(g.get("y1"), g["m1"], g["d1"], g["h1"], g["min1"], y_fallback)
    end = parse_dt(g.get("y2"), g["m2"], g["d2"], g["h2"], g["min2"], start.year)
    if end <= start:
        end = parse_dt(g.get("y2"), g["m2"], g["d2"], g["h2"], g["min2"], start.year + 1)
    hours = (end - start).total_seconds() / 3600
    if hours < 6 or hours > 24 * 100:
        return None
    return start, end


def parse_version_article(art: dict, ref: datetime) -> tuple[list[dict], dict[str, str], str]:
    html = art.get("articleContent") or ""
    text = strip_html(html)
    maint = extract_maint_start(text, ref)
    subjects = extract_subjects(text)
    version_banner = (art.get("suggestCover") or "") or first_image(html)
    events: list[dict] = []
    seen: set[str] = set()

    for pat in (BLOCK, QUOTE_BLOCK):
        for m in pat.finditer(text):
            name = (m.group("name") or m.groupdict().get("name") or "").strip()
            kind = (m.group("kind") or "").strip()
            if not name or SKIP_KIND.search(kind) or SKIP_KIND.search(name):
                continue
            ctx = m.groupdict().get("ctx") or ""
            if "永久" in ctx or "永久" in (m.group("body") or ""):
                # 版本更新后 ~ 明确结束日 仍保留；纯永久跳过
                if "版本更新后" in (m.group("body") or "") and m.group("m2"):
                    pass
                elif "永久" in ctx:
                    continue
            pair = ranges_from_match(m, maint, ref)
            if not pair:
                continue
            start, end = pair
            # skip pure maint window
            if (end - start).total_seconds() < 12 * 3600 and "维护" in name:
                continue
            key = f"{name}|{start.isoformat()}|{end.isoformat()}"
            if key in seen:
                continue
            seen.add(key)
            cat = wuwa_category(name, kind)
            header = f"{name}·{kind}" if kind else name
            events.append(
                {
                    "name": name,
                    "header": header[:40],
                    "start": start,
                    "end": end,
                    "category": cat,
                    "aid": art.get("articleId"),
                    "summary": "",
                    "version_banner": version_banner,
                }
            )

    # gacha names without explicit time → attach to version window if maint known
    if maint:
        # version end often ~40 days; use latest event end or +40d
        ver_end = max((e["end"] for e in events), default=maint)
        for gm in GACHA_NAME.finditer(text):
            name = (gm.group("a") or gm.group("b") or "").strip()
            if not name:
                continue
            key = f"gacha|{name}"
            if key in seen:
                continue
            seen.add(key)
            events.append(
                {
                    "name": name,
                    "header": f"{name}·唤取",
                    "start": maint,
                    "end": ver_end,
                    "category": "gacha",
                    "aid": art.get("articleId"),
                    "summary": "",
                    "fuzzy": True,
                    "version_banner": version_banner,
                }
            )
    return events, subjects, version_banner


def main() -> int:
    menu = http_get_json(BASE + "ArticleMenu.json", UA)
    if not isinstance(menu, list):
        raise RuntimeError("ArticleMenu 格式异常")

    # 优先最新版本说明
    notes = [
        a
        for a in menu
        if a.get("articleType") == 52 and "内容说明" in (a.get("articleTitle") or "")
    ]
    notes.sort(key=lambda a: a.get("startTime") or a.get("createTime") or "", reverse=True)

    ref = now_cn()
    collected: list[dict] = []
    subjects: dict[str, str] = {}
    for a in notes[:2]:
        aid = a["articleId"]
        detail = http_get_json(BASE + f"article/{aid}.json", UA)
        if not isinstance(detail, dict):
            continue
        print(f"  解析 {detail.get('articleTitle')} ({aid})")
        evs, subs, _vb = parse_version_article(detail, ref)
        collected.extend(evs)
        subjects.update(subs)

    print("  subjects", len(subjects))
    gk_rows = load_gamekee_covers()
    # 再捞已结束活动图，给系列复用（光影/呜呜等）
    try:
        raw_done = http_get_json(
            "https://www.gamekee.com/v1/activity/page-list"
            "?importance=0&sort=-1&keyword=&limit=80&page_no=1&status=2",
            {
                "game-alias": "mc",
                "Referer": "https://www.gamekee.com/mc/",
                "Accept": "application/json",
                "User-Agent": UA["User-Agent"],
            },
        )
        rows = raw_done.get("data") or []
        if isinstance(rows, dict):
            rows = rows.get("list") or []
        for it in rows:
            title = (it.get("title") or "").strip()
            pic = abs_url(
                it.get("big_picture") or it.get("picture") or "",
                "https://cdnimg-v2.gamekee.com/",
            )
            if title and pic:
                gk_rows.append((title, pic))
    except Exception:
        pass
    print("  gamekee covers", len(gk_rows))

    # 去重：同名保留时段最长且未结束优先
    best: dict[str, dict] = {}
    for e in collected:
        k = e["name"]
        prev = best.get(k)
        if not prev or (e["end"] - e["start"]) > (prev["end"] - prev["start"]):
            best[k] = e

    # 作战兜底：同版本只允许一张版本 KV（给时段最长的作战）
    combat_need = [
        e for e in best.values() if e["end"] >= ref and e["category"] == "combat"
    ]
    combat_need.sort(key=lambda x: (x["end"] - x["start"]), reverse=True)
    combat_fallback_name = combat_need[0]["name"] if combat_need else ""

    events = []
    for e in best.values():
        if e["end"] < ref:
            continue
        raw_vb = e.get("version_banner") or ""
        # 作战主活动独占版本 KV；拍照系列「光影瞬息」无独立图时允许用版本 KV
        vb = ""
        if e["name"] == combat_fallback_name:
            vb = raw_vb
        remote = resolve_banner(
            name=e["name"],
            category=e["category"],
            subjects=subjects,
            menu=menu,
            gk_rows=gk_rows,
            version_banner=vb,
        )
        banner = ""
        if remote:
            banner = cache_cover(
                f"wuwa-{e['aid']}-{e['name'][:12]}",
                remote,
                cover_referer(remote),
            )
        print("  cover", "ok" if banner else "none", e["aid"], len(banner or ""))
        stem = re.sub(r"[^\w\u4e00-\u9fff]+", "", e["name"])[:20]
        events.append(
            build_event(
                cid=f"wuwa-{e['aid']}-{stem}",
                title=e["name"],
                header=e["header"],
                banner=banner,
                link=f"{LINK}/detail/{e['aid']}",
                start=e["start"],
                end=e["end"],
                fuzzy=bool(e.get("fuzzy")),
                summary="",
                category=e["category"],
            )
        )

    events.sort(key=lambda x: (x["category"] != "combat", x.get("start") or ""))
    write_events(
        DATA / "wuwa.json",
        {
            "game": "鸣潮",
            "pending": False,
            "fetchedAt": ref.isoformat(),
            "count": len(events),
            "events": events,
            "source": BASE + "ArticleMenu.json",
            "notes": [
                "封面：独立公告 > Fandom 角色/武器图 > GameKee 系列图；不用版本总图凑数",
            ],
        },
    )
    print(f"[wuwa] {len(events)} 条进行中/预告")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
