#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""接入此前 pending 的游戏：NIKKE / 尘白 / 无期 / 少前2 / PVZ2 / 1999 等。"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin

from common import (
    DATA,
    TZ,
    allow_fuzzy_estimate,
    build_event,
    cache_cover,
    guess_category,
    http_get,
    http_get_json,
    is_bare_announce,
    now_cn,
    parse_ranges,
    pick_primary,
    strip_html,
    write_events,
)

PVZ_WIKI_API = "https://plantsvszombies.fandom.com/zh/api.php"
# 标题里出现则去 Wiki 取立绘（长词优先）
PVZ_WIKI_KEYS = sorted(
    [
        "向日葵",
        "双子向日葵",
        "豌豆射手",
        "寒冰射手",
        "双发射手",
        "坚果墙",
        "高坚果",
        "樱桃炸弹",
        "西瓜投手",
        "卷心菜投手",
        "玉米投手",
        "大嘴花",
        "地刺",
        "土豆雷",
        "窝瓜",
        "三叶草",
        "磁力菇",
        "胆小菇",
        "阳光菇",
        "大喷菇",
        "小喷菇",
        "魅惑菇",
        "冰西瓜",
        "火爆辣椒",
        "杨桃",
        "激光豆",
        "柠檬",
        "香蕉",
        "椰子加农炮",
        "僵尸",
        "路障僵尸",
        "铁桶僵尸",
        "舞王僵尸",
        "巨人僵尸",
        "伽刚特尔",
        "僵王",
        "植物大战僵尸2",
    ],
    key=len,
    reverse=True,
)


def abs_url(url: str, base: str = "") -> str:
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http://"):
        # 混合内容：强制 https（B 站封面等）
        return "https://" + url[len("http://") :]
    if url.startswith("http"):
        return url
    return urljoin(base or "https://example.com/", url)


def pvz_wiki_pageimage(title: str) -> str:
    try:
        data = http_get_json(
            PVZ_WIKI_API
            + "?"
            + urlencode(
                {
                    "action": "query",
                    "prop": "pageimages",
                    "titles": title,
                    "pithumbsize": 800,
                    "redirects": 1,
                    "format": "json",
                }
            ),
            {"User-Agent": "Mozilla/5.0 GameEventCal/1.1", "Accept": "application/json"},
        )
    except Exception:
        return ""
    for page in (data.get("query") or {}).get("pages", {}).values():
        if page.get("missing") is not None:
            continue
        thumb = page.get("thumbnail") or {}
        if thumb.get("source"):
            return thumb["source"]
    return ""


def pvz_wiki_cover(title: str) -> str:
    """从 Fandom Wiki 按标题关键词取图。"""
    blob = title or ""
    for key in PVZ_WIKI_KEYS:
        if key in blob:
            img = pvz_wiki_pageimage(key)
            if img:
                return img
    # 再试清理后的标题 opensearch
    q = re.sub(r"【[^】]*】", "", blob).strip()[:24]
    if len(q) >= 2:
        try:
            data = http_get_json(
                PVZ_WIKI_API
                + "?"
                + urlencode({"action": "opensearch", "search": q, "limit": 5, "format": "json"}),
                {"User-Agent": "Mozilla/5.0 GameEventCal/1.1", "Accept": "application/json"},
            )
            hits = data[1] if isinstance(data, list) and len(data) > 1 else []
            for hit in hits:
                img = pvz_wiki_pageimage(hit)
                if img:
                    return img
        except Exception:
            pass
    return pvz_wiki_pageimage("植物大战僵尸2")


def keep_event(ev: dict[str, Any], now: datetime) -> bool:
    if not ev.get("hasSchedule"):
        return False
    end = datetime.fromisoformat(ev["end"])
    # 已结束超过半天的丢掉
    return end >= now - timedelta(hours=12)


def sort_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rank = {"进行中": 0, "即将开始": 1, "已结束": 2}
    events.sort(key=lambda e: (rank.get(e.get("status", ""), 9), e.get("end") or "9999"))
    return events


def fetch_gamekee(
    *,
    game: str,
    alias: str,
    server_id: int,
    out_prefix: str,
    area_note: str = "",
) -> dict[str, Any]:
    """通用 GameKee 活动列表。"""
    now = now_cn()
    url = (
        "https://www.gamekee.com/v1/activity/page-list"
        f"?importance=0&sort=-1&keyword=&limit=80&page_no=1&serverId={server_id}&status=0"
    )
    raw = http_get_json(
        url,
        {
            "game-alias": alias,
            "Referer": "https://www.gamekee.com/",
            "Accept": "application/json",
        },
    )
    rows = raw.get("data") or []
    if isinstance(rows, dict):
        rows = rows.get("list") or []
    events: list[dict[str, Any]] = []
    notes: list[str] = []
    for it in rows:
        title = (it.get("title") or "").strip()
        if not title:
            continue
        begin = it.get("begin_at") or 0
        end = it.get("end_at") or 0
        if not begin or not end:
            continue
        start = datetime.fromtimestamp(int(begin), tz=TZ)
        end_dt = datetime.fromtimestamp(int(end), tz=TZ)
        if end_dt < now - timedelta(days=2):
            continue
        cid = str(it.get("id") or f"{begin}")
        pic = abs_url(
            it.get("big_picture") or it.get("picture") or "",
            "https://cdnimg-v2.gamekee.com/",
        )
        banner = (
            cache_cover(f"{out_prefix}-{cid}", pic, "https://www.gamekee.com/") if pic else ""
        )
        link = it.get("link_url") or f"https://www.gamekee.com/{alias}/{cid}.html"
        ev = build_event(
            cid=cid,
            title=title,
            header=title,
            banner=banner or pic,
            link=link,
            start=start,
            end=end_dt,
            category=guess_category(title),
            summary=title,
        )
        if keep_event(ev, now):
            events.append(ev)
    events = sort_events(events)
    notes.append(f"GameKee {alias} server={server_id} · {len(events)} 条")
    if area_note:
        notes.append(area_note)
    return {
        "game": game,
        "source": url,
        "fetchedAt": now.isoformat(),
        "timezone": "Asia/Shanghai",
        "pending": False,
        "count": len(events),
        "notes": notes,
        "events": events,
    }


# ───────────── NIKKE（GameKee：国服日历滞后，用外服进行中数据） ─────────────
def fetch_nikke() -> dict[str, Any]:
    return fetch_gamekee(
        game="胜利女神：NIKKE",
        alias="nikke",
        server_id=19,
        out_prefix="nikke",
        area_note="国服 GameKee 日历滞后，当前用外服进行中活动（时段接近）",
    )


# ───────────── 尘白禁区（官网栏目滞后；GameKee + 4.0 预告） ─────────────
def fetch_snowbreak() -> dict[str, Any]:
    now = now_cn()
    data = fetch_gamekee(
        game="尘白禁区",
        alias="snow",
        server_id=0,
        out_prefix="snow",
        area_note="官网公告栏目未更新到 3.7/4.0，先用 GameKee",
    )
    events = data["events"]
    notes = list(data.get("notes") or [])
    # 4.0 周年庆已知排期（社区/公告）：2026-07-16 起
    v40_start = datetime(2026, 7, 16, 10, 0, tzinfo=TZ)
    v40_end = datetime(2026, 8, 27, 4, 0, tzinfo=TZ)
    if v40_end >= now - timedelta(days=1):
        if not any("4.0" in (e.get("title") or "") or "空都" in (e.get("title") or "") for e in events):
            cover_url = ""
            for e0 in events:
                if e0.get("banner") and str(e0["banner"]).startswith("./"):
                    cover_url = e0["banner"]
                    break
            # GameKee 历史「空都演绎」/最新版本图作预告封面
            if not cover_url:
                try:
                    gk = http_get_json(
                        "https://www.gamekee.com/v1/activity/page-list"
                        "?importance=0&sort=-1&keyword=&limit=40&page_no=1&serverId=0&status=0",
                        {
                            "game-alias": "snow",
                            "Referer": "https://www.gamekee.com/",
                            "Accept": "application/json",
                        },
                    )
                    rows = gk.get("data") or []
                    if isinstance(rows, dict):
                        rows = rows.get("list") or []
                    prefer = [r for r in rows if "空都" in (r.get("title") or "")]
                    pool = prefer or rows[:5]
                    for it in pool:
                        pic = abs_url(
                            it.get("big_picture") or it.get("picture") or "",
                            "https://cdnimg-v2.gamekee.com/",
                        )
                        if not pic:
                            continue
                        cover_url = cache_cover("snow-4.0", pic, "https://www.gamekee.com/")
                        if cover_url:
                            break
                except Exception as e:
                    notes.append(f"4.0封面: {e}")
            if not cover_url:
                try:
                    listing = http_get_json(
                        "https://www.cbjq.com/api.php?op=search_api&action=get_article_list"
                        "&catid=7131&page=1&num=6&order_by=inputtime"
                    )
                    for it in (listing.get("data") or {}).get("list") or []:
                        thumb = abs_url(it.get("thumb") or "", "https://www.cbjq.com/")
                        if thumb:
                            cover_url = cache_cover("snow-4.0", thumb, "https://www.cbjq.com/")
                            if cover_url:
                                break
                except Exception:
                    pass
            ev = build_event(
                cid="snow-4.0-preview",
                title="4.0 周年庆「空都演绎」",
                header="4.0 周年庆版本即将开启",
                banner=cover_url or "",
                link="https://www.cbjq.com/",
                start=v40_start,
                end=v40_end,
                fuzzy=True,
                category="combat",
                summary="周年庆大版本（估时，以官网为准）",
            )
            events.append(ev)
            notes.append("补 4.0「空都演绎」预告（7/16 起，估时）")
    # 官网再扫一遍，有新时段则并入
    list_url = (
        "https://www.cbjq.com/api.php?op=search_api&action=get_article_list"
        "&catid=7131&page=1&num=12&order_by=inputtime"
    )
    try:
        listing = http_get_json(list_url)
        rows = (listing.get("data") or {}).get("list") or []
    except Exception as e:
        notes.append(f"官网列表失败: {e}")
        rows = []
    for it in rows[:8]:
        aid = it.get("id")
        title = (it.get("title") or "").strip()
        if not aid or not title or re.search(r"预约|问卷|防沉迷|实名", title):
            continue
        try:
            detail = http_get_json(
                f"https://www.cbjq.com/api.php?op=search_api&action=get_article_detail"
                f"&catid={it.get('catid') or 7131}&id={aid}"
            )
            body = (detail.get("data") or [{}])[0]
        except Exception:
            continue
        text = strip_html(body.get("content") or "")
        # 兼容「5月8日维护后 - 6月19日04:00」「5月22日10:00 - 6月19日04:00」
        text2 = re.sub(r"维护后", " 04:00", text)
        text2 = re.sub(r"(\d{1,2}月\d{1,2}日)(\d{1,2}:\d{2})", r"\1 \2", text2)
        try:
            ts = int(it.get("inputtime") or 0)
            ref = datetime.fromtimestamp(ts if ts < 1e12 else ts / 1000, tz=TZ)
        except Exception:
            ref = now
        ranges = parse_ranges(text2, ref)
        primary = pick_primary(ranges)
        if not primary:
            continue
        end = datetime.fromisoformat(primary["end"])
        if end < now - timedelta(days=2):
            continue
        start = datetime.fromisoformat(primary["start"])
        thumb = abs_url(it.get("thumb") or "", "https://www.cbjq.com/")
        banner = cache_cover(f"snow-{aid}", thumb, "https://www.cbjq.com/") if thumb else ""
        ev = build_event(
            cid=str(aid),
            title=title,
            header=title,
            banner=banner or thumb,
            link=it.get("url") or "https://www.cbjq.com/",
            start=start,
            end=end,
            ranges=ranges[:5],
            category=guess_category(title),
            summary=title,
        )
        if not any(e["id"] == ev["id"] for e in events):
            events.append(ev)
            print(f"  + snow-official [{ev['status']}] {title[:28]}")
    events = sort_events(events)
    data["events"] = events
    data["count"] = len(events)
    data["notes"] = notes
    data["source"] = f"{data['source']} + {list_url}"
    data["pending"] = False
    return data


# ───────────── 无期迷途 ─────────────
def fetch_ptn() -> dict[str, Any]:
    now = now_cn()
    list_url = "https://wqmt.aisnogames.com/api/news?page=1&pageSize=30"
    listing = http_get_json(list_url, {"Referer": "https://wqmt.aisnogames.com/"})
    rows = (listing.get("data") or {}).get("allNews") or []
    events: list[dict[str, Any]] = []
    notes: list[str] = []
    for it in rows:
        nid = it.get("id")
        title = (it.get("title") or "").strip()
        if not nid or not title:
            continue
        if re.search(r"防沉迷|实名|封禁|声明|协议|隐私", title):
            continue
        if is_bare_announce(title):
            continue
        try:
            detail = http_get_json(
                f"https://wqmt.aisnogames.com/api/news/{nid}",
                {"Referer": "https://wqmt.aisnogames.com/"},
            )
            body = detail.get("data")
            if isinstance(body, list):
                body = body[0] if body else {}
            body = body or {}
        except Exception as e:
            notes.append(f"{nid} 详情失败: {e}")
            continue
        html = body.get("content_html") or body.get("content") or ""
        text = strip_html(html)
        pub = body.get("publish_time") or it.get("publish_time") or ""
        try:
            ref = datetime.fromisoformat(str(pub).replace(" ", "T")).replace(tzinfo=TZ)
        except Exception:
            ref = now
        ranges = parse_ranges(text, ref)
        primary = pick_primary(ranges)
        fuzzy = False
        if not primary:
            # 短预告无时段：用发布日估 14 天（生日/卡池常见）
            if re.search(r"生日会|卡池|唤取|活动|限时", title):
                start = ref.replace(hour=4, minute=0, second=0, microsecond=0)
                end = start + timedelta(days=14)
                primary = {
                    "label": "估时",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "raw": "publish+14d",
                }
                fuzzy = True
            else:
                notes.append(f"{nid} 跳过无时段：{title[:24]}")
                continue
        start = datetime.fromisoformat(primary["start"])
        end = datetime.fromisoformat(primary["end"])
        if end < now - timedelta(days=2):
            continue
        cover = abs_url(it.get("cover") or body.get("cover") or "", "https://wqmt.aisnogames.com/")
        banner = cache_cover(f"ptn-{nid}", cover, "https://wqmt.aisnogames.com/") if cover else ""
        link = it.get("href") or f"https://wqmt.aisnogames.com/news/{nid}"
        if link.startswith("/"):
            link = "https://wqmt.aisnogames.com" + link
        ev = build_event(
            cid=str(nid),
            title=title,
            header=title,
            banner=banner or cover,
            link=link,
            start=start,
            end=end,
            ranges=[primary],
            fuzzy=fuzzy,
            category=guess_category(title),
            summary=title,
        )
        events.append(ev)
        print(f"  + ptn [{ev['status']}] {title[:28]}")
    events = sort_events(events)
    return {
        "game": "无期迷途",
        "source": list_url,
        "fetchedAt": now.isoformat(),
        "timezone": "Asia/Shanghai",
        "pending": False,
        "count": len(events),
        "notes": notes,
        "events": events,
    }


# ───────────── 少女前线2 ─────────────
def fetch_gfl2() -> dict[str, Any]:
    now = now_cn()
    base = "https://gf2-web-preregister-api.sunborngame.com"
    events: list[dict[str, Any]] = []
    notes: list[str] = []
    # 轮播图作备选封面
    rotations: list[dict[str, Any]] = []
    try:
        rot = http_get_json(f"{base}/website/rotation", {"Referer": "https://gf2-cn.sunborngame.com/"})
        rotations = (rot.get("data") or []) if isinstance(rot.get("data"), list) else []
    except Exception:
        pass

    for type_id in (1, 2, 3):
        try:
            listing = http_get_json(
                f"{base}/website/news_list/{type_id}?page=1&limit=12",
                {"Referer": "https://gf2-cn.sunborngame.com/"},
            )
        except Exception as e:
            notes.append(f"list {type_id} fail: {e}")
            continue
        rows = (listing.get("data") or {}).get("list") or []
        for it in rows:
            nid = it.get("Id") or it.get("id")
            title = (it.get("Title") or it.get("title") or "").strip()
            if not nid or not title:
                continue
            if re.search(r"防沉迷|实名|封禁|协议|隐私|声明|问卷", title):
                continue
            if is_bare_announce(title):
                continue
            try:
                detail = http_get_json(
                    f"{base}/website/news/{nid}",
                    {"Referer": "https://gf2-cn.sunborngame.com/"},
                )
                body = detail.get("data") or {}
            except Exception as e:
                notes.append(f"{nid} 详情失败: {e}")
                continue
            html = body.get("Content") or body.get("content") or ""
            text = strip_html(html)
            date_s = body.get("Date") or it.get("Date") or ""
            try:
                ref = datetime.fromisoformat(str(date_s).replace(" ", "T")).replace(tzinfo=TZ)
            except Exception:
                ref = now
            ranges = parse_ranges(text, ref)
            primary = pick_primary(ranges)
            fuzzy = False
            if not primary:
                # 壁纸/纯更新公告不估时段
                if is_bare_announce(title) or not allow_fuzzy_estimate(title):
                    continue
                if re.search(r"活动|卡池|共鸣|限时|作战", title):
                    start = ref
                    end = ref + timedelta(days=14)
                    primary = {
                        "label": "估时",
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "raw": "Date+14d",
                    }
                    fuzzy = True
                else:
                    continue
            start = datetime.fromisoformat(primary["start"])
            end = datetime.fromisoformat(primary["end"])
            if end < now - timedelta(days=2):
                continue
            # 封面：正文首图 / 轮播
            imgs = re.findall(r'src=["\'](https?://[^"\']+\.(?:png|jpg|jpeg|webp))["\']', html, re.I)
            pic = imgs[0] if imgs else ""
            if not pic and rotations:
                pic = rotations[0].get("PicUrl") or rotations[0].get("picUrl") or ""
            banner = cache_cover(f"gfl2-{nid}", pic, "https://gf2-cn.sunborngame.com/") if pic else ""
            link = f"https://gf2-cn.sunborngame.com/news/{nid}"
            ev = build_event(
                cid=str(nid),
                title=title,
                header=title,
                banner=banner or pic,
                link=link,
                start=start,
                end=end,
                ranges=ranges[:5] or [primary],
                fuzzy=fuzzy,
                category=guess_category(title),
                summary=title,
            )
            # 去重
            if any(e["id"] == ev["id"] for e in events):
                continue
            events.append(ev)
            print(f"  + gfl2 [{ev['status']}] {title[:28]}")
    events = sort_events(events)
    return {
        "game": "少女前线2：追放",
        "source": f"{base}/website/news_list",
        "fetchedAt": now.isoformat(),
        "timezone": "Asia/Shanghai",
        "pending": False,
        "count": len(events),
        "notes": notes,
        "events": events,
    }


# ───────────── PVZ2 国服 ─────────────
def fetch_pvz2() -> dict[str, Any]:
    now = now_cn()
    events: list[dict[str, Any]] = []
    notes: list[str] = []
    for type_id in (1, 10):
        try:
            listing = http_get_json(
                f"https://pvz2.hrgame.com.cn/news/list/{type_id}",
                {"Referer": "https://pvz2.hrgame.com.cn/"},
            )
        except Exception as e:
            notes.append(f"list {type_id}: {e}")
            continue
        rows = listing.get("data") or []
        for it in rows:
            nid = it.get("id")
            title = (it.get("title") or "").strip()
            if not nid or not title:
                continue
            if re.search(r"防沉迷|实名|封禁|协议", title):
                continue
            # 详情 HTML
            text = ""
            html = ""
            try:
                html = http_get(
                    f"https://pvz2.hrgame.com.cn/news/{nid}",
                    {"Referer": "https://pvz2.hrgame.com.cn/", "Accept": "text/html"},
                ).decode("utf-8", "replace")
                m = re.search(r'id=["\']detail["\'][^>]*>([\s\S]*?)</div>', html, re.I)
                chunk = m.group(1) if m else html
                text = strip_html(chunk)
            except Exception as e:
                notes.append(f"{nid} 详情: {e}")
            time_s = it.get("time") or ""
            try:
                ref = datetime.fromisoformat(str(time_s).replace(" ", "T")).replace(tzinfo=TZ)
            except Exception:
                ref = now
            ranges = parse_ranges(text, ref) if text else []
            primary = pick_primary(ranges)
            fuzzy = False
            if not primary:
                # 前瞻/整活等纯资讯不估 30 天假周期
                if is_bare_announce(title) or not allow_fuzzy_estimate(title):
                    notes.append(f"{nid} 纯公告无时段，跳过：{title[:36]}")
                    continue
                start = ref
                end = ref + timedelta(days=30)
                primary = {
                    "label": "活动周期（估）",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "raw": "list.time+30d",
                }
                fuzzy = True
            start = datetime.fromisoformat(primary["start"])
            end = datetime.fromisoformat(primary["end"])
            if end < now - timedelta(days=2):
                continue
            pic = abs_url(it.get("image") or "", "https://pvz2.hrgame.com.cn/")
            if not pic and html:
                imgs = re.findall(
                    r'src=["\'](https?://[^"\']+\.(?:png|jpg|jpeg|webp))["\']',
                    html,
                    re.I,
                )
                pic = abs_url(imgs[0], "https://pvz2.hrgame.com.cn/") if imgs else ""
            # B 站外链封面要带 Referer；失败再走 Wiki
            banner = ""
            if pic:
                ref = (
                    "https://www.bilibili.com/"
                    if "hdslb.com" in pic or "bilibili.com" in pic
                    else "https://pvz2.hrgame.com.cn/"
                )
                banner = cache_cover(f"pvz2-{nid}", pic, ref)
                if banner.startswith("http"):
                    banner = ""  # 未落盘的远程链在 HTTPS 页常裂图
            if not banner:
                wiki_pic = pvz_wiki_cover(title)
                if wiki_pic:
                    banner = cache_cover(
                        f"pvz2-{nid}-wiki",
                        wiki_pic,
                        "https://plantsvszombies.fandom.com/",
                    )
                    if banner.startswith("http"):
                        banner = wiki_pic  # wikia 一般可直链
            link = it.get("link") or f"https://pvz2.hrgame.com.cn/news/{nid}"
            if link.startswith("http://"):
                link = "https://" + link[len("http://") :]
            ev = build_event(
                cid=str(nid),
                title=title,
                header=title,
                banner=banner,
                link=link,
                start=start,
                end=end,
                ranges=ranges[:4] or [primary],
                fuzzy=fuzzy,
                category=guess_category(title),
                summary=(it.get("description") or title)[:120],
            )
            if any(e["id"] == ev["id"] for e in events):
                continue
            events.append(ev)
            print(f"  + pvz2 [{ev['status']}] {title[:28]}")
    events = sort_events(events)
    return {
        "game": "植物大战僵尸2",
        "source": "https://pvz2.hrgame.com.cn/news/list/1",
        "fetchedAt": now.isoformat(),
        "timezone": "Asia/Shanghai",
        "pending": False,
        "count": len(events),
        "notes": notes,
        "events": events,
    }


# ───────────── 重返未来 1999（B 站游戏中心 + 官网兜底） ─────────────
def fetch_reverse1999() -> dict[str, Any]:
    now = now_cn()
    notes: list[str] = []
    events: list[dict[str, Any]] = []
    source = ""
    # biligame 多 id 试探（命中带「1999/重返」标题的）
    bili_ids = [1014, 1036, 1047, 1055, 1066, 1077, 1088, 1099, 1111, 1122, 746, 980, 990]
    rows: list[dict[str, Any]] = []
    for gid in bili_ids:
        try:
            u = (
                "https://api.biligame.com/news/list.action"
                f"?gameExtensionId={gid}&positionId=2&pageNum=1&pageSize=15&typeId="
            )
            d = http_get_json(u)
            data = d.get("data") or []
            if not data:
                continue
            t0 = data[0].get("title") or ""
            if not re.search(r"1999|重返|雷霆", t0) and gid not in (1014, 1036):
                # 仍接受有「活动/版本」的列表，靠正文过滤
                if not any(re.search(r"活动|版本|更新|卡池|招募", x.get("title") or "") for x in data[:3]):
                    continue
            source = u
            rows = data
            notes.append(f"biligame gameExtensionId={gid}")
            break
        except Exception:
            continue

    if not rows:
        # 官网 HTML
        try:
            html = http_get(
                "https://1999.leiting.com/",
                {"Referer": "https://1999.leiting.com/", "Accept": "text/html"},
            ).decode("utf-8", "replace")
            source = "https://1999.leiting.com/"
            for m in re.finditer(
                r'["\']([^"\']*news_detail[^"\']*)["\']',
                html,
                re.I,
            ):
                href = abs_url(m.group(1), "https://1999.leiting.com/")
                rows.append({"title": "", "url": href, "id": safe_hash(href)})
            notes.append(f"官网链 {len(rows)} 条")
        except Exception as e:
            notes.append(f"官网: {e}")

    for i, it in enumerate(rows[:18]):
        title = (it.get("title") or it.get("name") or "").strip()
        link = abs_url(
            it.get("url") or it.get("link") or it.get("pcUrl") or "",
            "https://game.bilibili.com/",
        )
        if it.get("id") and not link:
            link = f"https://www.biligame.com/detail/?id={it.get('id')}"
        html = ""
        text = ""
        if link and "http" in link:
            try:
                html = http_get(link, {"Referer": "https://1999.leiting.com/"}).decode(
                    "utf-8", "replace"
                )
                text = strip_html(html)
                if not title:
                    tm = re.search(r"<title>([^<]+)</title>", html, re.I)
                    title = strip_html(tm.group(1) if tm else "").split("_")[0].strip()
            except Exception:
                pass
        if not title or re.search(
            r"防沉迷|实名|协议|隐私|客服|未成年|限时通知|节假日|劳动节|清明|端午|春节|元旦",
            title,
        ):
            continue
        pub = it.get("createTime") or it.get("publishTime") or it.get("ctime") or ""
        try:
            if isinstance(pub, (int, float)) or (isinstance(pub, str) and str(pub).isdigit()):
                ref = datetime.fromtimestamp(int(pub), tz=TZ)
            else:
                ref = datetime.fromisoformat(str(pub).replace(" ", "T")).replace(tzinfo=TZ)
        except Exception:
            ref = now
        ranges = parse_ranges(text, ref) if text else []
        primary = pick_primary(ranges)
        fuzzy = False
        if not primary:
            if re.search(r"活动|卡池|唤取|版本|更新|复刻|招募|限时活动|副本|推演", title):
                start = ref.replace(hour=5, minute=0, second=0, microsecond=0)
                end = start + timedelta(days=14)
                primary = {
                    "label": "估时",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "raw": "估",
                }
                fuzzy = True
            else:
                continue
        start = datetime.fromisoformat(primary["start"])
        end = datetime.fromisoformat(primary["end"])
        if end < now - timedelta(days=2):
            continue
        imgs = re.findall(r'src=["\'](https?://[^"\']+\.(?:png|jpg|jpeg|webp))["\']', html, re.I)
        pic = abs_url(it.get("cover") or (imgs[0] if imgs else ""), "https://1999.leiting.com/")
        banner = (
            cache_cover(f"r1999-{safe_hash(title)}", pic, "https://1999.leiting.com/") if pic else ""
        )
        ev = build_event(
            cid=str(it.get("id") or f"r1999-{i}"),
            title=title,
            header=title,
            banner=banner or pic,
            link=link or "https://1999.leiting.com/",
            start=start,
            end=end,
            ranges=ranges[:4] or [primary],
            fuzzy=fuzzy,
            category=guess_category(title),
            summary=title,
        )
        if any(e["title"] == title for e in events):
            continue
        events.append(ev)
        print(f"  + 1999 [{ev['status']}] {title[:28]}")
    # 官方日历源滞后时：补联动预告（社区公开排期）
    collab_start = datetime(2026, 7, 23, 5, 0, tzinfo=TZ)
    collab_end = datetime(2026, 8, 13, 4, 59, tzinfo=TZ)
    site_cover = ""
    site_covers: list[str] = []
    try:
        home = http_get(
            "https://1999.leiting.com/",
            {"Referer": "https://1999.leiting.com/", "Accept": "text/html"},
        ).decode("utf-8", "replace")
        pics = re.findall(
            r"https?://pic\.leiting\.com/upload/[^\"'\s]+\.(?:jpg|jpeg|png|webp)",
            home,
            re.I,
        )
        pics = [u for u in pics if not re.search(r"logo|icon", u, re.I)]
        for i, pu in enumerate(pics[:6]):
            c = cache_cover(f"r1999-home-{i}", pu, "https://1999.leiting.com/")
            if not c:
                continue
            # 跳过过小的图标/装饰图
            try:
                sz = (Path("public") / c.lstrip("./")).stat().st_size
            except OSError:
                sz = 0
            if sz and sz < 40000:
                continue
            site_covers.append(c)
        if not site_covers and pics:
            c = cache_cover("r1999-home", pics[0], "https://1999.leiting.com/")
            if c:
                site_covers.append(c)
        site_cover = site_covers[0] if site_covers else ""
    except Exception as e:
        notes.append(f"官网封面: {e}")

    if collab_end >= now - timedelta(days=1):
        if not any("原子之心" in (e.get("title") or "") for e in events):
            events.append(
                build_event(
                    cid="r1999-atomic-heart",
                    title="×《原子之心》联动版本",
                    header="金属剧作分析 · 双子限定招募",
                    banner=site_covers[0] if site_covers else site_cover or "",
                    link="https://1999.leiting.com/",
                    start=collab_start,
                    end=collab_end,
                    fuzzy=True,
                    category="combat",
                    summary="7/23 全球同步联动（估时，以官网为准）",
                )
            )
            notes.append("补《原子之心》联动预告 7/23（估时）")
        if not any("湖的涟漪" in (e.get("title") or "") for e in events):
            events.append(
                build_event(
                    cid="r1999-lake-ripple",
                    title="卡池「湖的涟漪」",
                    header="自选六星保底卡池",
                    banner=site_covers[1] if len(site_covers) > 1 else "",
                    link="https://1999.leiting.com/",
                    start=collab_start,
                    end=collab_end,
                    fuzzy=True,
                    category="gacha",
                    summary="联动版本同期卡池（估时）",
                )
            )

    events = sort_events(events)
    pending = len(events) == 0
    return {
        "game": "重返未来：1999",
        "source": source or "https://1999.leiting.com/",
        "fetchedAt": now.isoformat(),
        "timezone": "Asia/Shanghai",
        "pending": pending,
        "count": len(events),
        "notes": notes or (["暂无解析到进行中活动"] if pending else []),
        "events": events,
    }


def safe_hash(s: str) -> str:
    import hashlib

    return hashlib.md5(s.encode("utf-8")).hexdigest()[:8]


# ───────────── 炉石 / 永劫 / 三角洲：尽力 HTML ─────────────
def fetch_hearthstone() -> dict[str, Any]:
    now = now_cn()
    notes: list[str] = []
    events: list[dict[str, Any]] = []
    try:
        html = http_get(
            "https://hs.blizzard.cn/news",
            {"Referer": "https://hs.blizzard.cn/", "Accept": "text/html"},
        ).decode("utf-8", "replace")
    except Exception as e:
        return _pending("炉石传说", "https://hs.blizzard.cn/news", [str(e)])

    hrefs = re.findall(r"https://hs\.blizzard\.cn/news/\d{8}/\d+_\d+(?:\.html)?", html, re.I)
    hrefs += re.findall(r"https://hs\.blizzard\.cn/news/\d+/index\.html", html, re.I)
    hrefs += [
        "https://hs.blizzard.cn" + h
        for h in re.findall(r'href=["\'](/news/(?:\d{8}/\d+_\d+(?:\.html)?|\d+/index\.html))["\']', html, re.I)
    ]
    seen: set[str] = set()
    for href in hrefs[:28]:
        link = href.split("#")[0].rstrip("/")
        if re.search(r"/news/\d{8}/\d+_\d+$", link):
            link += ".html"
        if link in seen:
            continue
        seen.add(link)
        try:
            page = http_get(link, {"Referer": "https://hs.blizzard.cn/"}).decode("utf-8", "replace")
        except Exception as e:
            notes.append(f"{link}: {e}")
            continue
        title_m = re.search(r"<title>([^<]+)</title>", page, re.I)
        page_title = re.sub(r"\s+", " ", strip_html(title_m.group(1) if title_m else "")).strip()
        # 站点全局 h1 常年是扩展包名，不能当标题
        title = re.sub(r"\s*[-_|].*(?:炉石传说|Hearthstone).*$", "", page_title, flags=re.I).strip()
        title = re.sub(r"\s+", " ", title)
        if not title or title in ("炉石传说", "炉石传说官网"):
            continue
        # 电竞/商城/客服/攻略引导类不进日历
        if re.search(
            r"电竞|观赛|公开赛|精英挑战|报名|直播间|客服|官网$|结束后的下一步|阵容公布",
            title,
        ):
            continue
        text = strip_html(page)
        ref = now
        ts_m = re.search(r'data-timestamp=["\'](\d+)["\']', page)
        if ts_m:
            ts = int(ts_m.group(1))
            if ts > 1e12:
                ts //= 1000
            if 1_500_000_000 < ts < 2_200_000_000:
                try:
                    ref = datetime.fromtimestamp(ts, tz=TZ)
                except (OSError, OverflowError, ValueError):
                    ref = now
        dm = re.search(r"/news/(\d{8})/", link)
        if dm and ref == now:
            y, mo, d = int(dm.group(1)[:4]), int(dm.group(1)[4:6]), int(dm.group(1)[6:8])
            ref = datetime(y, mo, d, 10, 0, tzinfo=TZ)
        ranges = parse_ranges(text, ref)
        primary = pick_primary(ranges)
        fuzzy = False
        if not primary:
            # 扩展包上线/合集营销等纯公告不估 28 天
            if is_bare_announce(title) or not allow_fuzzy_estimate(title):
                continue
            if re.search(r"乱斗|酒馆|赛季|通行证|冒险|奖励路线|补丁|试用|活动", title):
                start = ref
                end = ref + timedelta(days=28)
                primary = {
                    "label": "估时",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "raw": "估",
                }
                fuzzy = True
            else:
                continue
        start = datetime.fromisoformat(primary["start"])
        end = datetime.fromisoformat(primary["end"])
        if end < now - timedelta(days=2):
            continue
        imgs = [
            u
            for u in re.findall(
                r'(?:src|data-src)=["\'](https?://[^"\']+\.(?:png|jpg|jpeg|webp))["\']',
                page,
                re.I,
            )
            if not re.search(r"logo|icon|avatar|emoji|sprite|1x1", u, re.I)
        ]
        # 去重保序
        imgs = list(dict.fromkeys(imgs))
        pic = imgs[0] if imgs else ""
        banner = cache_cover(f"hs-{safe_hash(link)}", pic, "https://hs.blizzard.cn/") if pic else ""
        # 补丁说明：正文里多段活动窗口 → 拆成独立条目
        if re.search(r"补丁说明", title) and len(ranges) >= 2:
            for ri, r in enumerate(ranges[:6]):
                rs = datetime.fromisoformat(r["start"])
                re_ = datetime.fromisoformat(r["end"])
                if re_ < now - timedelta(days=2):
                    continue
                if (re_ - rs).days > 45:
                    continue
                raw = r.get("raw") or ""
                ctx = ""
                # 在正文中找日期句前后的活动名
                idx = text.find(raw[:20]) if raw else -1
                if idx >= 0:
                    snip = text[max(0, idx - 60) : idx + len(raw) + 80]
                    qm = re.search(r"[「\"“]([^」\"”]{2,20})[」\"”]", snip)
                    if qm:
                        ctx = qm.group(1)
                    else:
                        km = re.search(
                            r"(酒馆乱斗|乱斗|酒馆战棋|神话英雄皮肤|英雄皮肤|超级合集|"
                            r"战网商城|神秘礼物|追赶包|试用卡牌|异画卡牌|异画|宠物乐园|"
                            r"翡翠梦境|迷宫系统|奖励路线)[^，。！!\n]{0,6}",
                            snip,
                        )
                        if km:
                            ctx = km.group(0)
                ctx = re.sub(r"\s+", "", ctx or "")
                ctx = re.sub(r"(将于|并于|会在).*$", "", ctx)
                ctx = re.sub(r"[！!。．].*$", "", ctx)
                if len(ctx) > 16 or re.search(r"该活动|二合一|结束后", ctx):
                    ctx = ""
                span = f"{rs.month}/{rs.day}-{re_.month}/{re_.day}"
                lab = (r.get("label") or "").strip()
                if ctx:
                    sub_title = f"{ctx}（{span}）"
                elif lab and lab not in ("活动时间", "估时") and len(lab) <= 12:
                    sub_title = f"{lab}（{span}）"
                else:
                    sub_title = f"限时活动（{span}）"
                # 多段活动尽量用不同配图；图不够则只给首条封面，避免五张同图
                sub_pic = imgs[ri] if ri < len(imgs) else ""
                sub_banner = (
                    cache_cover(f"hs-{safe_hash(link)}-{ri}", sub_pic, "https://hs.blizzard.cn/")
                    if sub_pic
                    else (banner if ri == 0 else "")
                )
                ev = build_event(
                    cid=f"{safe_hash(link)}-{ri}",
                    title=sub_title,
                    header=sub_title,
                    banner=sub_banner,
                    link=link,
                    start=rs,
                    end=re_,
                    ranges=[r],
                    fuzzy=False,
                    category="event",
                    summary=title,
                )
                if any(e["title"] == sub_title for e in events):
                    continue
                events.append(ev)
                print(f"  + hs [{ev['status']}] {sub_title[:28]}")
            continue
        ev = build_event(
            cid=safe_hash(link),
            title=title,
            header=title,
            banner=banner or pic,
            link=link,
            start=start,
            end=end,
            ranges=ranges[:3] or [primary],
            fuzzy=fuzzy,
            category=guess_category(title),
            summary=title,
        )
        events.append(ev)
        print(f"  + hs [{ev['status']}] {title[:28]}")
    events = sort_events(events)
    return {
        "game": "炉石传说",
        "source": "https://hs.blizzard.cn/news",
        "fetchedAt": now.isoformat(),
        "timezone": "Asia/Shanghai",
        "pending": len(events) == 0,
        "count": len(events),
        "notes": notes,
        "events": events,
    }


def fetch_naraka() -> dict[str, Any]:
    now = now_cn()
    notes: list[str] = []
    events: list[dict[str, Any]] = []
    list_url = "https://www.yjwujian.cn/news/"
    try:
        html = http_get(
            list_url,
            {"Referer": "https://www.yjwujian.cn/", "Accept": "text/html"},
        ).decode("utf-8", "replace")
    except Exception as e:
        return _pending("永劫无间", list_url, [str(e)])

    links = re.findall(
        r"https://www\.yjwujian\.cn/news/(?:update|official)/\d{8}/[^\"'\s<]+",
        html,
        re.I,
    )
    links += [
        "https://www.yjwujian.cn" + h
        for h in re.findall(r"/news/(?:update|official)/\d{8}/[^\"'\s<]+", html, re.I)
    ]
    seen: set[str] = set()
    for link in links[:22]:
        link = link.split("#")[0].rstrip("/")
        if not link.endswith(".html"):
            continue
        if link in seen:
            continue
        seen.add(link)
        try:
            page = http_get(link, {"Referer": "https://www.yjwujian.cn/"}).decode("utf-8", "replace")
        except Exception as e:
            notes.append(f"{link}: {e}")
            continue
        title_m = re.search(r"<title>([^<]+)</title>", page, re.I)
        title = strip_html(title_m.group(1) if title_m else "").split("_")[0].split("-")[0].strip()
        title = re.sub(r"\s*[|｜].*$", "", title).strip()
        if not title or re.search(r"封禁|违规|防沉迷|FAQ|账号转移|城市联赛|武神杯", title):
            continue
        if is_bare_announce(title):
            continue
        text = strip_html(page)
        text2 = re.sub(r"更新后", " 10:00", text)
        ranges = parse_ranges(text2, now)
        primary = pick_primary(ranges)
        fuzzy = False
        if not primary:
            if not allow_fuzzy_estimate(title):
                continue
            dm = re.search(r"/(\d{8})/", link)
            if dm:
                y, mo, d = int(dm.group(1)[:4]), int(dm.group(1)[4:6]), int(dm.group(1)[6:8])
                start = datetime(y, mo, d, 10, 0, tzinfo=TZ)
            else:
                start = now
            end = start + timedelta(days=21)
            primary = {
                "label": "活动周期（估）",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "raw": "估",
            }
            fuzzy = True
        start = datetime.fromisoformat(primary["start"])
        end = datetime.fromisoformat(primary["end"])
        if end < now - timedelta(days=2):
            continue
        imgs = re.findall(
            r'(?:src|data-src)=["\'](https?://[^"\']+\.(?:png|jpg|jpeg|webp))["\']',
            page,
            re.I,
        )
        pic = next((u for u in imgs if not re.search(r"logo|icon|qrcode", u, re.I)), imgs[0] if imgs else "")
        banner = cache_cover(f"naraka-{safe_hash(link)}", pic, "https://www.yjwujian.cn/") if pic else ""
        ev = build_event(
            cid=safe_hash(link),
            title=title,
            header=title,
            banner=banner or pic,
            link=link,
            start=start,
            end=end,
            ranges=ranges[:3] or [primary],
            fuzzy=fuzzy,
            category=guess_category(title),
            summary=title,
        )
        if any(e["title"] == title for e in events):
            continue
        events.append(ev)
        print(f"  + naraka [{ev['status']}] {title[:28]}")
    events = sort_events(events)
    return {
        "game": "永劫无间",
        "source": list_url,
        "fetchedAt": now.isoformat(),
        "timezone": "Asia/Shanghai",
        "pending": len(events) == 0,
        "count": len(events),
        "notes": notes,
        "events": events,
    }


def fetch_delta() -> dict[str, Any]:
    now = now_cn()
    notes: list[str] = []
    events: list[dict[str, Any]] = []
    try:
        raw = http_get(
            "https://df.qq.com/main.shtml",
            {"Referer": "https://df.qq.com/", "Accept": "text/html"},
        )
        # 腾讯页可能 gbk
        try:
            html = raw.decode("utf-8")
        except UnicodeDecodeError:
            html = raw.decode("gbk", "replace")
    except Exception as e:
        return _pending("三角洲行动", "https://df.qq.com/main.shtml", [str(e)])

    ids = list(dict.fromkeys(re.findall(r"newsdetail\.html\?id=(\d+)", html, re.I)))
    seen: set[str] = set()
    for nid in ids[:16]:
        if nid in seen:
            continue
        seen.add(nid)
        link = f"https://df.qq.com/cp/a20240906main/newsdetail.html?id={nid}"
        try:
            raw = http_get(link, {"Referer": "https://df.qq.com/"})
            try:
                page = raw.decode("utf-8")
            except UnicodeDecodeError:
                page = raw.decode("gbk", "replace")
        except Exception as e:
            notes.append(f"{nid}: {e}")
            continue
        title_m = re.search(r"<title>([^<]+)</title>", page, re.I)
        title = strip_html(title_m.group(1) if title_m else "")
        # 去掉站点后缀，勿按「三角洲」切开（标题本身常含游戏名）
        title = re.split(r"-{2,}|_| \| |—|–", title)[0].strip()
        title = re.sub(r"-腾讯游戏.*$", "", title).strip()
        h1 = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", page, re.I)
        if h1:
            t2 = strip_html(h1.group(1))
            if 4 <= len(t2) <= 80:
                title = t2
        if not title or len(title) < 2:
            title = f"公告 {nid}"
        if re.search(r"封禁|防沉迷|实名|客服", title):
            continue
        if is_bare_announce(title):
            continue
        text = strip_html(page)
        ranges = parse_ranges(text, now)
        primary = pick_primary(ranges)
        fuzzy = False
        if not primary:
            if not allow_fuzzy_estimate(title):
                continue
            if re.search(r"活动|赛季|作战|通行证|限时|版本", title):
                # 赛季页常无精确截止：按约 6 周估
                start = now.replace(hour=10, minute=0, second=0, microsecond=0)
                days = 45 if "赛季" in title else 21
                end = start + timedelta(days=days)
                primary = {
                    "label": "赛季周期（估）" if "赛季" in title else "估时",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "raw": "估",
                }
                fuzzy = True
            else:
                continue
        start = datetime.fromisoformat(primary["start"])
        end = datetime.fromisoformat(primary["end"])
        if end < now - timedelta(days=2):
            continue
        imgs = re.findall(
            r'(?:src|data-src)=["\'](https?://[^"\']+\.(?:png|jpg|jpeg|webp))["\']',
            page,
            re.I,
        )
        pic = next((u for u in imgs if not re.search(r"logo|icon|qrcode", u, re.I)), imgs[0] if imgs else "")
        banner = cache_cover(f"delta-{nid}", pic, "https://df.qq.com/") if pic else ""
        if not banner:
            # 官网详情常无图：Steam 头图兜底
            banner = cache_cover(
                "delta-kv",
                "https://cdn.cloudflare.steamstatic.com/steam/apps/2507950/header.jpg",
                "https://store.steampowered.com/",
            )
        # 标题去游戏名前缀噪音
        short = re.sub(r"^《三角洲行动》", "", title).strip(" ，,!")
        if any((e.get("title") == short or e.get("title") == title) for e in events):
            continue
        ev = build_event(
            cid=str(nid),
            title=short or title,
            header=short or title,
            banner=banner or pic,
            link=link,
            start=start,
            end=end,
            ranges=ranges[:3] or [primary],
            fuzzy=fuzzy,
            category="combat" if "赛季" in title else guess_category(title),
            summary=title,
        )
        events.append(ev)
        print(f"  + delta [{ev['status']}] {ev['title'][:28]}")
    events = sort_events(events)
    return {
        "game": "三角洲行动",
        "source": "https://df.qq.com/main.shtml",
        "fetchedAt": now.isoformat(),
        "timezone": "Asia/Shanghai",
        "pending": len(events) == 0,
        "count": len(events),
        "notes": notes,
        "events": events,
    }


def _pending(name: str, source: str, notes: list[str]) -> dict[str, Any]:
    return {
        "game": name,
        "source": source,
        "fetchedAt": now_cn().isoformat(),
        "timezone": "Asia/Shanghai",
        "pending": True,
        "count": 0,
        "notes": notes,
        "events": [],
    }


JOBS = [
    ("nikke.json", fetch_nikke),
    ("snowbreak.json", fetch_snowbreak),
    ("ptn.json", fetch_ptn),
    ("gfl2.json", fetch_gfl2),
    ("pvz2.json", fetch_pvz2),
    ("reverse1999.json", fetch_reverse1999),
    ("hearthstone.json", fetch_hearthstone),
    ("naraka.json", fetch_naraka),
    ("delta.json", fetch_delta),
]


def main() -> int:
    codes = 0
    only = set(sys.argv[1:]) if len(sys.argv) > 1 else None
    for fname, fn in JOBS:
        stem = fname.replace(".json", "")
        if only and stem not in only and fname not in only:
            continue
        print(f"\n===== {fname} =====")
        try:
            data = fn()
            write_events(DATA / fname, data)
            print(f"  count={data.get('count')} pending={data.get('pending')}")
        except Exception as e:
            print(f"[err] {fname}: {e}")
            codes = 1
    return codes


if __name__ == "__main__":
    raise SystemExit(main())
