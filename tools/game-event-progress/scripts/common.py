#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三游戏共用：请求、封面缓存、时间解析、事件状态。"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
COVER_DIR = ROOT / "public" / "covers"
TZ = timezone(timedelta(hours=8))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GameEventCal/1.1"


def now_cn() -> datetime:
    return datetime.now(TZ)


def http_get(url: str, headers: dict[str, str] | None = None, timeout: int = 40) -> bytes:
    h = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        h.update(headers)
    req = Request(url, headers=h)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_get_json(url: str, headers: dict[str, str] | None = None) -> Any:
    return json.loads(http_get(url, headers).decode("utf-8"))


def strip_html(html: str) -> str:
    text = unescape(html or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\\n", "\n").replace("\\u003c", "<").replace("\\u003e", ">")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def safe_stem(name: str) -> str:
    ascii_part = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-")[:40]
    if not ascii_part or re.search(r"[\u4e00-\u9fff]", name):
        digest = hashlib.md5(name.encode("utf-8")).hexdigest()[:10]
        ascii_part = (ascii_part + "-" if ascii_part else "") + digest
    return ascii_part or "cover"


def cache_cover(cid: str, url: str, referer: str = "") -> str:
    if not url:
        return ""
    COVER_DIR.mkdir(parents=True, exist_ok=True)
    ext = ".jpg"
    low = url.lower().split("?")[0]
    if low.endswith(".png"):
        ext = ".png"
    elif low.endswith(".webp"):
        ext = ".webp"
    elif low.endswith(".jpeg"):
        ext = ".jpg"
    # 文件名带 URL 指纹，换源图时不会命中旧缓存
    url_fp = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    dest = COVER_DIR / f"{safe_stem(cid)}-{url_fp}{ext}"
    if dest.exists() and dest.stat().st_size > 8000:
        return f"./covers/{dest.name}"
    if dest.exists() and dest.stat().st_size <= 8000:
        try:
            dest.unlink()
        except OSError:
            pass
    try:
        data = http_get(
            url,
            {
                "Referer": referer or url,
                "Accept": "image/*,*/*",
            },
        )
        if len(data) < 8000:
            return ""
        dest.write_bytes(data)
        print(f"    [cover] {dest.name} ({len(data)} bytes)")
        return f"./covers/{dest.name}"
    except Exception as e:
        print(f"    [cover] 失败 {cid}: {e}")
        return ""


def make_dt(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


def parse_ranges(text: str, ref: datetime | None = None) -> list[dict[str, Any]]:
    """从正文抽起止时间（支持中文月日 / 2026/07/16）。"""
    ref = ref or now_cn()
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    patterns = [
        # 07月10日 12:00 - 07月17日 03:59
        re.compile(
            r"(?P<label>[【\[]?[^：:\n]{0,24}?(?:时间|开放|开启|结束|截止)[^：:\n]{0,12})?[：:]?\s*"
            r"(?P<m1>\d{1,2})月(?P<d1>\d{1,2})日\s*(?P<h1>\d{1,2})[:：](?P<min1>\d{2})"
            r"\s*[-–—~～至到]\s*"
            r"(?P<m2>\d{1,2})月(?P<d2>\d{1,2})日\s*(?P<h2>\d{1,2})[:：](?P<min2>\d{2})",
            re.I,
        ),
        # 7月8日至7月29日（无时刻，默认 10:00→04:00）
        re.compile(
            r"(?P<label>[【\[]?[^：:\n]{0,24}?(?:时间|开放|开启|结束|截止|期间)[^：:\n]{0,12})?[：:]?\s*"
            r"(?P<m1>\d{1,2})月(?P<d1>\d{1,2})日\s*[-–—~～至到]\s*"
            r"(?P<m2>\d{1,2})月(?P<d2>\d{1,2})日",
            re.I,
        ),
        # 2026/07/16 06:00 - 2026/07/30 04:00
        re.compile(
            r"(?P<label>[【\[]?[^：:\n]{0,24}?(?:时间|开放|开启|结束|截止)[^：:\n]{0,12})?[：:]?\s*"
            r"(?P<y1>20\d{2})[/-](?P<m1>\d{1,2})[/-](?P<d1>\d{1,2})\s*(?P<h1>\d{1,2})[:：](?P<min1>\d{2})"
            r"\s*[-–—~～至到]\s*"
            r"(?:(?P<y2>20\d{2})[/-])?(?P<m2>\d{1,2})[/-](?P<d2>\d{1,2})\s*(?P<h2>\d{1,2})[:：](?P<min2>\d{2})",
            re.I,
        ),
        # 2026年7月10日12:00 - 2026年7月24日03:59
        re.compile(
            r"(?P<label>[【\[]?[^：:\n]{0,24}?(?:时间|开放|开启|结束|截止)[^：:\n]{0,12})?[：:]?\s*"
            r"(?P<y1>20\d{2})年(?P<m1>\d{1,2})月(?P<d1>\d{1,2})日\s*(?P<h1>\d{1,2})[:：](?P<min1>\d{2})"
            r"\s*[-–—~～至到]\s*"
            r"(?:(?P<y2>20\d{2})年)?(?P<m2>\d{1,2})月(?P<d2>\d{1,2})日\s*(?P<h2>\d{1,2})[:：](?P<min2>\d{2})",
            re.I,
        ),
        # 2026年北京时间07月02日8:00 结束 / 单点截止
        re.compile(
            r"(?P<y1>20\d{2})年(?:北京时间)?(?P<m1>\d{1,2})月(?P<d1>\d{1,2})日\s*"
            r"(?P<h1>\d{1,2})[:：](?P<min1>\d{2})\s*(?P<tail>结束|截止|维护)",
            re.I,
        ),
    ]

    for pat in patterns:
        for m in pat.finditer(text):
            g = m.groupdict()
            label = (g.get("label") or "活动时间").strip(" ：:")
            y1 = int(g["y1"]) if g.get("y1") else ref.year
            y2 = int(g["y2"]) if g.get("y2") else y1
            m1, d1 = int(g["m1"]), int(g["d1"])
            # 单点截止：用 ref→截止
            if g.get("tail") and not g.get("m2"):
                end = make_dt(y1, m1, d1, int(g["h1"]), int(g["min1"]))
                start = ref.replace(hour=10, minute=0, second=0, microsecond=0)
                if start >= end:
                    start = end - timedelta(days=21)
                key = (start.isoformat(), end.isoformat())
                if key in seen:
                    continue
                hours = (end - start).total_seconds() / 3600
                if hours < 1 or hours > 24 * 120:
                    continue
                seen.add(key)
                found.append(
                    {
                        "label": label or "赛季/活动",
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "raw": m.group(0)[:140],
                    }
                )
                continue
            m2, d2 = int(g["m2"]), int(g["d2"])
            if y2 == y1 and (m2, d2) < (m1, d1):
                y2 += 1
            h1 = int(g["h1"]) if g.get("h1") is not None else 10
            min1 = int(g["min1"]) if g.get("min1") is not None else 0
            h2 = int(g["h2"]) if g.get("h2") is not None else 4
            min2 = int(g["min2"]) if g.get("min2") is not None else 0
            start = make_dt(y1, m1, d1, h1, min1)
            end = make_dt(y2, m2, d2, h2, min2)
            key = (start.isoformat(), end.isoformat())
            if key in seen:
                continue
            hours = (end - start).total_seconds() / 3600
            if hours < 1 or hours > 24 * 120:
                continue
            seen.add(key)
            found.append(
                {
                    "label": label,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "raw": m.group(0)[:140],
                }
            )
    return found


def pick_primary(ranges: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not ranges:
        return None
    prefer = ("活动持续", "关卡", "活动时间", "开放时间", "作战", "挑战", "总力", "开启")
    for p in prefer:
        for r in ranges:
            if p in r["label"]:
                return r
    # 避开商店/兑换长尾巴
    combat = [r for r in ranges if not re.search(r"商店|兑换|招募", r["label"])]
    pool = combat or ranges
    return max(
        pool,
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
    return "未知"


def remain_text(start: datetime | None, end: datetime | None, now: datetime) -> str:
    if start and now < start:
        until = start - now
        days = until.days
        hours = until.seconds // 3600
        if days > 0:
            return f"{days}天后"
        if hours > 0:
            return f"{hours}小时后"
        return "即将开始"
    if end and now < end:
        left = end - now
        days = left.days
        hours = left.seconds // 3600
        if days > 0:
            return f"剩{days}天{hours}时" if hours else f"剩{days}天"
        if hours > 0:
            return f"剩{hours}小时"
        return "将结束"
    return "已结束"


def progress_of(start: datetime | None, end: datetime | None, now: datetime) -> float:
    if not start or not end or end <= start:
        return 0.0
    if now <= start:
        return 0.0
    if now >= end:
        return 100.0
    return max(0.0, min(100.0, (now - start).total_seconds() / (end - start).total_seconds() * 100))


def is_bare_announce(title: str) -> bool:
    """纯公告/资讯：不应进进度日历（或绝不能估假起止）。"""
    t = title or ""
    # 「赛季/活动现已上线」是真实进行中内容，不算纯公告
    if re.search(r"现已上线|扩展包现已", t) and re.search(
        r"赛季|活动|作战|通行证|限时|版本", t
    ):
        pass
    elif re.search(
        r"现已上线|扩展包现已|合集福利|预购即用|集卡活动",
        t,
    ):
        return True
    return bool(
        re.search(
            r"预下载|更新预告|更新维护预告|维护预告|结算公告|研发通讯|内容更新说明|"
            r"壁纸|意见征集|征集活动|奖励公示|封禁处理|处罚账号|封禁公告|"
            r"【整活】|【前瞻】|战绩更新|生日贺礼|"
            r"版本更新公告|停服维护更新公告|更新公告|"
            r"正在为你匹配|匹配旗鼓相当|FAQ|账号转移",
            t,
        )
    )


def allow_fuzzy_estimate(title: str) -> bool:
    """无完整起止时，是否允许单点估时。卡池/限时活动可以，纯公告不行。"""
    if is_bare_announce(title):
        return False
    t = title or ""
    return bool(
        re.search(
            r"寻访|卡池|招募|祈愿|唤取|调频|跃迁|特许寻访|"
            r"限时活动|【活动】|作战|挑战|危机合约|丰碑|签到|"
            r"活动开启|通行证|赛季|周年|五周年|外观|轮换|乱斗|酒馆|冒险|"
            r"奖励路线|补丁说明|试用",
            t,
        )
    )


def guess_category(title: str, header: str = "", typ: str = "") -> str:
    """combat=作战 / gacha=卡池 / web=网页 / event=活动（签到/维护等）"""
    blob = f"{title} {header} {typ}"
    if re.search(r"网页活动|H5|web\s*event|外链活动|浏览器", blob, re.I):
        return "web"
    if re.search(r"(?:^|【|\s)网页(?:活动|】)|新网页活动|官网活动|专题页", blob, re.I):
        return "web"
    if re.search(r"寻访|卡池|祈愿|跃迁|调频|招募|UP|特选|特许寻访|常驻祈愿|唤取|建造|共鸣", blob, re.I):
        return "gacha"
    if re.search(
        r"签到|登录|维护|闪断|修复|问卷|兑换|商店|特卖|申领|创作|征集|直播|周边|邮件|补偿|封禁|更新说明|优化|拍照|委托|回礼|时装|涂装|皮肤",
        blob,
        re.I,
    ):
        return "event"
    return "combat"


def build_event(
    *,
    cid: str,
    title: str,
    header: str,
    banner: str,
    link: str,
    start: datetime | None,
    end: datetime | None,
    ranges: list[dict[str, Any]] | None = None,
    kind: str = "live",
    fuzzy: bool = False,
    summary: str = "",
    category: str | None = None,
    body: str = "",
) -> dict[str, Any]:
    now = now_cn()
    st = status_of(start, end, now)
    pct = progress_of(start, end, now)
    days = None
    if start and end and end > start:
        total = (end - start).total_seconds() / 86400
        elapsed = max(0.0, (now - start).total_seconds() / 86400)
        remain = max(0.0, (end - now).total_seconds() / 86400)
        days = {
            "elapsedDays": round(min(elapsed, total), 1),
            "remainDays": round(remain, 1),
            "totalDays": round(total, 1),
        }
    cat = category or guess_category(title, header)
    out: dict[str, Any] = {
        "id": cid,
        "title": title,
        "header": header or title,
        "banner": banner,
        "link": link,
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "status": st,
        "remain": remain_text(start, end, now),
        "progress": round(pct, 1),
        "days": days,
        "hasSchedule": bool(start and end),
        "kind": "preview" if st == "即将开始" else ("done" if st == "已结束" else "live"),
        "fuzzy": fuzzy,
        "category": cat,
        "allRanges": ranges or [],
        # 无正文时留空，前端不展示假「说明」
        "summary": summary or "",
    }
    if body:
        out["body"] = body
    return out


# 由 update.py / fetch_all.py --dry-run 设置（子进程读环境变量）
DRY_RUN = os.environ.get("GEP_DRY_RUN", "").strip() in ("1", "true", "yes")


def validate_payload(payload: dict[str, Any], *, path: Path | None = None) -> list[str]:
    """抓取结果最低限度校验，返回问题列表（空=通过）。"""
    errs: list[str] = []
    if not isinstance(payload, dict):
        return ["payload 不是 dict"]
    evs = payload.get("events")
    if not isinstance(evs, list):
        errs.append("缺少 events 列表")
        return errs
    if payload.get("count") is not None and int(payload["count"]) != len(evs):
        errs.append(f"count={payload.get('count')} 与 events 长度 {len(evs)} 不一致")
    for i, e in enumerate(evs):
        if not isinstance(e, dict):
            errs.append(f"events[{i}] 非对象")
            continue
        if not (e.get("title") or e.get("header")):
            errs.append(f"events[{i}] 缺 title/header")
        if e.get("hasSchedule"):
            if not e.get("start") or not e.get("end"):
                errs.append(f"events[{i}] hasSchedule 但缺 start/end")
            else:
                try:
                    s = datetime.fromisoformat(str(e["start"]))
                    en = datetime.fromisoformat(str(e["end"]))
                    if en <= s:
                        errs.append(f"events[{i}] end<=start")
                except Exception:
                    errs.append(f"events[{i}] 时间无法解析")
    return errs


def write_events(path: Path, payload: dict[str, Any]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    new_events = payload.get("events") or []
    # 抓取偶发空结果时，保留上一份有效数据，避免定时任务把页面刷空
    if path.exists() and not new_events and payload.get("pending"):
        try:
            old = json.loads(path.read_text(encoding="utf-8-sig"))
            old_events = old.get("events") or []
            if old_events:
                notes = list(payload.get("notes") or [])
                notes.append(f"抓取为空，保留旧数据 {len(old_events)} 条")
                payload = {
                    **payload,
                    "pending": False,
                    "count": len(old_events),
                    "events": old_events,
                    "notes": notes,
                    "keptPrevious": True,
                }
                print(f"[keep] {path.name} 抓取为空，保留旧 {len(old_events)} 条")
        except Exception:
            pass
    problems = validate_payload(payload, path=path)
    if problems:
        for p in problems[:8]:
            print(f"[validate] {path.name}: {p}")
        if len(problems) > 8:
            print(f"[validate] …共 {len(problems)} 项")
    if DRY_RUN:
        print(
            f"[dry-run] 跳过写入 {path.name} · "
            f"{payload.get('count', len(payload.get('events', [])))} 条"
        )
        return
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] 写入 {path} · {payload.get('count', len(payload.get('events', [])))} 条")
