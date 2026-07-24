#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取终末地官网公告（RSC bulletins），解析可打活动 / 卡池时段。"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DATA,
    TZ,
    allow_fuzzy_estimate,
    build_event,
    cache_cover,
    http_get,
    is_bare_announce,
    make_dt,
    now_cn,
    parse_ranges,
    strip_html,
    write_events,
)

NEWS_URL = "https://endfield.hypergryph.com/news"
DETAIL_URL = "https://endfield.hypergryph.com/news/{cid}"

KEEP = re.compile(
    r"危机合约|重燃测试|挑战|丰碑|作战|活动开启|内容更新|版本更新|限时挑战|影拓|版本预|核心章节|"
    r"寻访|卡池|特许寻访|标准寻访|机密圣所",
    re.I,
)
SKIP = re.compile(
    r"封禁|支付|启动器|征集|创作|小红书|研发通讯|问卷|云·",
    re.I,
)

# 开放时间：2026/06/26 12:00（服务器时间） - 版本更新维护前
OPEN_UNTIL_MAINT = re.compile(
    r"(?:开放时间|活动时间|活动开放时间)[：:]\s*"
    r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})\s*(\d{1,2})[:：](\d{2})"
    r"[^\n]{0,40}?(?:版本更新维护前|下次版本更新维护前)"
)
MAINT_AT = re.compile(
    r"(?:版本更新(?:停机)?维护|更新维护)[^\n]{0,40}?"
    r"(?:于\s*)?(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(\d{1,2})[:：](\d{2})"
    r"|"
    r"(?:版本更新(?:停机)?维护|更新维护)[^\n]{0,40}?"
    r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})\s*(\d{1,2})[:：](\d{2})"
)
MAINT_AT2 = re.compile(
    r"计划将于\s*(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(\d{1,2})[:：](\d{2})"
)

# 版本正文里成组的时段块
BLOCK_START = re.compile(
    r"(?m)^[·•\-\s]*("
    r"开放时间|活动时间|活动开放时间|"
    r"「[^」]{2,24}」开放时间"
    r")[：:]"
)
NAMED_QUOTE = re.compile(r"「([^」]{2,24})」")
REWARD_ITEM = re.compile(r"【([^】]{1,40})】")

CAT_LABEL = {"gacha": "卡池", "event": "活动", "combat": "作战", "web": "网页"}

# 列表里未必出现、但有独立配图的关联公告
EXTRA_COVER_CIDS = (
    "0425",  # 危机合约 / 机密圣所
    "6093",  # 染赤申领
    "4771",  # 卡缪征集
)
EXTRA_COVER_TITLES = {
    "0425": "「危机合约 重燃测试作战」内容更新说明",
    "6093": "「染赤申领」限时特卖说明",
    "4771": "「逐罪者」卡缪小红书特别征集活动",
}

# 活动名/关键词 → 优先匹配的公告关键词（标题命中即用其封面）
COVER_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("机密圣所", ("危机合约", "机密圣所", "重燃测试")),
    ("危机合约", ("危机合约", "重燃测试")),
    ("丰碑", ("丰碑", "影拓")),
    ("影拓", ("丰碑", "影拓")),
    ("死寂争鸣", ("丰碑", "影拓", "死寂")),
    ("选剑演武", ("选剑", "藏剑")),
    ("逐罪者", ("逐罪者", "卡缪")),
    ("夜趋逐罪", ("逐罪者", "卡缪", "夜趋")),
    ("卡缪", ("逐罪者", "卡缪")),
    ("拳出无悔", ("拳出无悔", "弭弗")),
    ("弭弗", ("拳出无悔", "弭弗")),
    ("染赤申领", ("染赤申领", "申领")),
    ("绛结申领", ("绛结", "申领")),
    ("以拳问心", ("以拳问心", "藏剑")),
    ("亡者之舞", ("亡者之舞",)),
    ("拍照", ("拍照", "墨绘")),
    ("每日补给", ("理智", "补给")),
    ("寻遗散记", ("寻遗散记", "版本更新说明")),
]


def extract_bulletins(rsc_text: str) -> list[dict]:
    i = rsc_text.find('"bulletins":[')
    if i < 0:
        return []
    chunk = rsc_text[i : i + 120000]
    start = chunk.find("[")
    depth = 0
    end = None
    for j, ch in enumerate(chunk[start:], start):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = j + 1
                break
    if end is None:
        return []
    return json.loads(chunk[start:end])


def fetch_list() -> list[dict]:
    body = http_get(
        NEWS_URL,
        {
            "Accept": "text/x-component",
            "RSC": "1",
            "Referer": "https://endfield.hypergryph.com/news",
        },
    ).decode("utf-8", "ignore")
    items = extract_bulletins(body)
    print(f"[EF] bulletins {len(items)}")
    return items


def fetch_detail_rsc(cid: str) -> str:
    return http_get(
        DETAIL_URL.format(cid=cid),
        {
            "Accept": "text/x-component",
            "RSC": "1",
            "Referer": "https://endfield.hypergryph.com/news",
        },
    ).decode("utf-8", "replace")


def fetch_detail_text(cid: str) -> str:
    """从 RSC 里抽公告正文，避免 unicode_escape 把中文弄坏。"""
    body = fetch_detail_rsc(cid)
    chunks = re.findall(r"<p[\s\S]{0,80}?>[\s\S]{0,3000}?</p>", body)
    if chunks:
        return strip_html("\n".join(chunks))
    text = body.replace("\\n", "\n").replace('\\"', '"')
    text = text.replace("\\u003c", "<").replace("\\u003e", ">")
    text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)
    return strip_html(text)


def detail_cover_urls(cid: str) -> list[str]:
    """公告详情里的上传图（去重保序）。"""
    try:
        body = fetch_detail_rsc(cid)
    except Exception:
        return []
    urls = re.findall(
        r"https://web\.hycdn\.cn/upload/image/\d{8}/[a-f0-9]{32}\.(?:jpg|jpeg|png|webp)",
        body,
        re.I,
    )
    out: list[str] = []
    seen: set[str] = set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def build_cover_bank(items: list[dict]) -> list[dict]:
    """收集可用封面：列表 cover + 关联公告详情图。"""
    bank: list[dict] = []
    seen_url: set[str] = set()

    def add(cid: str, title: str, url: str, weight: int = 1) -> None:
        url = (url or "").strip()
        if not url or url in seen_url:
            return
        seen_url.add(url)
        bank.append(
            {
                "cid": str(cid),
                "title": title or "",
                "url": url,
                "weight": weight,
            }
        )

    for it in items:
        cid = str(it.get("cid") or "")
        title = (it.get("title") or "").strip()
        cover = (it.get("cover") or "").strip()
        if cover:
            add(cid, title, cover, 3)
        # 详情多图：首图常等于列表 cover，取第 2 张作补充
        for i, u in enumerate(detail_cover_urls(cid)[:3]):
            add(cid, title, u, 2 if i == 0 else 1)

    for cid in EXTRA_COVER_CIDS:
        urls = detail_cover_urls(cid)
        if not urls:
            continue
        title = EXTRA_COVER_TITLES.get(cid, f"extra-{cid}")
        for i, u in enumerate(urls[:3]):
            add(cid, title, u, 4 if i == 0 else 2)

    print(f"[EF] cover bank {len(bank)}")
    return bank


def pick_cover_url(name: str, category: str, bank: list[dict], *, forbid: set[str] | None = None) -> str:
    """按活动名匹配封面；禁止直接拿版本总图凑数。"""
    forbid = forbid or set()
    name = (name or "").strip()
    if not name or not bank:
        return ""

    # 1) 标题直接包含活动名
    scored: list[tuple[int, str]] = []
    for b in bank:
        if b["url"] in forbid:
            continue
        title = b["title"]
        score = 0
        if name and name in title:
            score += 50 + b["weight"]
        for key, hints in COVER_HINTS:
            if key in name or name in key:
                if any(h in title for h in hints):
                    score += 40 + b["weight"]
        if category == "gacha" and re.search(r"寻访|申领|卡缪|弭弗", title):
            if any(k in name for k in ("逐罪", "拳出", "申领", "卡缪", "弭弗")):
                score += 20
        if category == "combat" and re.search(r"危机合约|圣所|丰碑|影拓", title):
            if any(k in name for k in ("圣所", "丰碑", "影拓", "选剑", "死寂", "合约")):
                score += 25
        if score:
            scored.append((score, b["url"]))
    if scored:
        scored.sort(key=lambda x: -x[0])
        return scored[0][1]

    # 2) 分类弱匹配（仍避开版本更新说明总图）
    for b in bank:
        if b["url"] in forbid:
            continue
        title = b["title"]
        if "版本更新说明" in title:
            continue
        if category == "gacha" and re.search(r"寻访|申领|卡缪|弭弗", title):
            return b["url"]
        if category == "combat" and re.search(r"危机合约|圣所|研发通讯", title):
            return b["url"]
    # 3) 活动：可用版本详情副图 / 研发通讯图（已 forbid 主 KV）
    if category == "event":
        for b in bank:
            if b["url"] in forbid:
                continue
            if re.search(r"版本更新说明|研发通讯|寻遗散记", b["title"]):
                return b["url"]
    return ""


def short_name(title: str) -> str:
    m = re.search(r"「([^」]+)」", title)
    if m:
        return m.group(1)[:28]
    return re.sub(r"说明|开启|更新", "", title).strip()[:28]


def is_playable(title: str) -> bool:
    if re.search(r"寻访|卡池|申领", title):
        return True
    if is_bare_announce(title):
        return False
    if SKIP.search(title) and not re.search(r"危机合约|版本更新|版本预|机密圣所", title):
        return False
    if SKIP.search(title) and not KEEP.search(title):
        return False
    return bool(KEEP.search(title))


def find_next_maint(texts: list[str], now: datetime) -> datetime | None:
    cands: list[datetime] = []
    for text in texts:
        for m in MAINT_AT2.finditer(text):
            y, mo, d, h, mi = map(int, m.groups())
            cands.append(make_dt(y, mo, d, h, mi))
        for m in MAINT_AT.finditer(text):
            g = m.groups()
            if g[0]:
                y, mo, d, h, mi = map(int, g[:5])
            else:
                y, mo, d, h, mi = map(int, g[5:])
            cands.append(make_dt(y, mo, d, h, mi))
    future = [t for t in cands if t > now - timedelta(hours=6)]
    if future:
        return min(future)
    return min(cands) if cands else None


def parse_ef_ranges(text: str, now: datetime, next_maint: datetime | None) -> list[dict]:
    ranges = parse_ranges(text, now)
    for m in OPEN_UNTIL_MAINT.finditer(text):
        y, mo, d, h, mi = map(int, m.groups())
        start = make_dt(y, mo, d, h, mi)
        end = next_maint or (start + timedelta(days=21))
        if end <= start:
            end = start + timedelta(days=14)
        ranges.append(
            {
                "label": "开放至版本维护前",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "raw": m.group(0)[:80],
            }
        )
    return ranges


def pick_best_range(ranges: list[dict], now: datetime) -> dict | None:
    """优先进行中 → 即将开始 → 跨度最长。"""
    if not ranges:
        return None
    live, soon, rest = [], [], []
    for r in ranges:
        s = datetime.fromisoformat(r["start"])
        e = datetime.fromisoformat(r["end"])
        if (e - s).total_seconds() < 20 * 3600:
            continue  # 跳过纯维护窗
        if s <= now <= e:
            live.append(r)
        elif now < s:
            soon.append(r)
        else:
            rest.append(r)

    def span(r: dict) -> float:
        return (
            datetime.fromisoformat(r["end"]) - datetime.fromisoformat(r["start"])
        ).total_seconds()

    if live:
        return max(live, key=span)
    if soon:
        return min(soon, key=lambda r: datetime.fromisoformat(r["start"]))
    recent = [
        r for r in rest if datetime.fromisoformat(r["end"]) >= now - timedelta(days=2)
    ]
    if recent:
        return max(recent, key=span)
    return None


def ranges_from_when(when: str, now: datetime, next_maint: datetime | None) -> list[dict]:
    """解析单行开放时间文案。"""
    when = (when or "").strip()
    blob = f"开放时间：{when}"
    ranges = parse_ef_ranges(blob, now, next_maint)
    if ranges:
        return ranges
    # 「xxx」版本开启后 - 2026/06/26 11:59
    m = re.search(
        r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})\s*(\d{1,2})[:：](\d{2})\s*$",
        when,
    )
    if m and ("开启后" in when or "更新后" in when):
        y, mo, d, h, mi = map(int, m.groups())
        end = make_dt(y, mo, d, h, mi)
        # 版本开启估为维护窗结束日附近；无更好信息时用 end-14d
        start = end - timedelta(days=14)
        return [
            {
                "label": "开放时间",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "raw": when[:80],
                "fuzzy": True,
            }
        ]
    # 开启后 - 版本更新维护前
    if ("开启后" in when or "更新后" in when) and "维护前" in when and next_maint:
        start = next_maint - timedelta(days=40)
        return [
            {
                "label": "开放至版本维护前",
                "start": start.isoformat(),
                "end": next_maint.isoformat(),
                "raw": when[:80],
                "fuzzy": True,
            }
        ]
    return parse_ranges(blob, now)


def clean_body(text: str, *, limit: int = 6000) -> str:
    """去掉过长修复列表，保留说明重点。"""
    t = (text or "").strip()
    if not t:
        return ""
    cut = re.search(r"(?m)^[·•\-\s]*(?:优化了|修复了)", t)
    if cut and cut.start() > 400:
        t = t[: cut.start()].rstrip() + "\n…"
    if len(t) > limit:
        t = t[:limit].rstrip() + "\n…"
    return t


def highlight_summary(block: str, name: str = "") -> str:
    """卡片摘要：名称 + 奖励关键词。"""
    rewards = REWARD_ITEM.findall(block)
    uniq: list[str] = []
    for r in rewards:
        if r not in uniq:
            uniq.append(r)
        if len(uniq) >= 4:
            break
    parts = []
    if name:
        parts.append(name)
    # 取说明行
    for line in block.splitlines():
        if re.search(r"(寻访|申领|活动)说明", line):
            s = re.sub(r"^[·•\-\s]+", "", line).strip()
            s = re.sub(r"^(?:寻访|申领|活动)说明[：:]\s*", "", s)
            if s:
                parts.append(s[:100])
            break
    if uniq:
        parts.append("奖励：" + "、".join(f"【{x}】" for x in uniq[:3]))
    return " · ".join(parts)[:220]


def classify_block(block: str, when_line: str) -> tuple[str, str]:
    """返回 (category, display_name)。"""
    blob = when_line + "\n" + block
    if re.search(r"寻访说明", block):
        m = re.search(r"寻访说明[：:]\s*「([^」]+)」", block)
        mq = NAMED_QUOTE.search(block)
        name = (m.group(1) if m else "") or (mq.group(1) if mq else "")
        return "gacha", name or "特许寻访"
    if re.search(r"申领说明", block):
        m = re.search(r"申领说明[：:]\s*「([^」]+)」", block)
        name = m.group(1) if m else ""
        return "gacha", name or "武器申领"
    # 作战向：机密圣所 / 丰碑 / 影拓 等优先
    if re.search(r"机密圣所|危机合约|丰碑|影拓|选剑演武|死寂争鸣", blob):
        m = re.search(
            r"「(机密圣所|[^」]*(?:丰碑|影拓|合约|选剑演武|死寂争鸣)[^」]*)」",
            blob,
        ) or NAMED_QUOTE.search(blob)
        return "combat", (m.group(1) if m else "作战挑战")
    m_named = re.search(r"「([^」]{2,24})」开放时间", when_line)
    if m_named:
        name = m_named.group(1)
        cat = "combat" if re.search(r"圣所|合约|丰碑|影拓|挑战|作战", name + block) else "event"
        return cat, name
    desc = ""
    for line in block.splitlines():
        if "活动说明" in line:
            desc = line
            break
    if re.search(r"签到", desc + block):
        vm = re.search(r"【([^】]*?(?:寻访凭证|凭证)[^】]*)】", block)
        if vm:
            tag = re.sub(r"(寻访)?凭证$", "", vm.group(1)).strip("· ")
            return "event", f"{tag}签到" if tag else "签到"
        m = NAMED_QUOTE.search(desc) or NAMED_QUOTE.search(block)
        return "event", (m.group(1) if m else "签到")
    if re.search(r"拍照", desc + block):
        return "event", "拍照任务"
    if re.search(r"每日完成指定任务|理智补给|理智消耗许可", desc + block):
        return "event", "每日补给"
    m = NAMED_QUOTE.search(desc) or NAMED_QUOTE.search(block)
    if m:
        return "event", m.group(1)
    return "event", "限时活动"


def split_schedule_blocks(text: str) -> list[dict]:
    """把版本说明拆成时段块。"""
    starts = list(BLOCK_START.finditer(text))
    if not starts:
        return []
    blocks: list[dict] = []
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        chunk = text[m.start() : end].strip()
        # 块太短或纯维护补偿跳过
        if len(chunk) < 20:
            continue
        if re.search(r"更新维护补偿|问题修复补偿|发放时间|发放条件", chunk) and not re.search(
            r"寻访说明|活动说明|申领说明|机密圣所", chunk
        ):
            continue
        first = chunk.splitlines()[0]
        when = re.sub(r"^[·•\-\s]+", "", first)
        when = re.sub(r"^(?:开放时间|活动时间|活动开放时间|「[^」]+」开放时间)[：:]\s*", "", when)
        cat, name = classify_block(chunk, first)
        # 无说明的「活动开放时间 / 活动内容更新」壳子块跳过（具名时段在后续块）
        if not re.search(r"(寻访|申领|活动)说明|「[^」]+」开放时间", chunk):
            if re.search(r"活动开放时间|活动内容更新时间", first):
                continue
        if name == "限时活动" and not re.search(r"活动说明", chunk):
            continue
        blocks.append(
            {
                "when": when.strip(),
                "name": name.strip(),
                "category": cat,
                "block": chunk,
                "when_line": first,
            }
        )
    return blocks


def label_for(cat: str, name: str) -> str:
    prefix = CAT_LABEL.get(cat, "活动")
    name = (name or "").strip()
    if not name:
        return prefix
    if name.startswith(prefix):
        return name
    return f"{prefix} · {name}"


def enrich_ranges_from_blocks(
    blocks: list[dict],
    now: datetime,
    next_maint: datetime | None,
) -> list[dict]:
    """版本总览用的带分类标签时段列表。"""
    out: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for b in blocks:
        ranges = ranges_from_when(b["when"], now, next_maint)
        if not ranges:
            continue
        # 跳过「于3次特许寻访后结束」这类无可靠绝对结束日
        if "次「特许寻访」后" in b["when"] or "次特许寻访后" in b["when"]:
            continue
        primary = pick_best_range(ranges, now) or ranges[0]
        end = datetime.fromisoformat(primary["end"])
        if end < now - timedelta(days=1):
            continue
        key = (b["category"], b["name"], primary["start"], primary["end"])
        if key in seen:
            continue
        seen.add(key)
        item = dict(primary)
        item["label"] = label_for(b["category"], b["name"])
        item["category"] = b["category"]
        out.append(item)
    return out


def events_from_blocks(
    *,
    blocks: list[dict],
    now: datetime,
    next_maint: datetime | None,
    cover_bank: list[dict],
    version_cover: str,
    source_cid: str,
    version_title: str,
) -> list[dict]:
    """从版本说明块生成细分卡片。"""
    out: list[dict] = []
    seen: set[str] = set()
    used_urls: set[str] = set()
    forbid = {version_cover} if version_cover else set()
    for b in blocks:
        if "次「特许寻访」后" in b["when"] or "次特许寻访后" in b["when"]:
            continue  # 武器申领相对次数，无绝对时段
        ranges = ranges_from_when(b["when"], now, next_maint)
        primary = pick_best_range(ranges, now)
        if not primary and ranges:
            primary = ranges[0]
        if not primary:
            continue
        start = datetime.fromisoformat(primary["start"])
        end = datetime.fromisoformat(primary["end"])
        if end < now - timedelta(days=1):
            continue
        name = b["name"]
        cat = b["category"]
        if name in ("限时活动",) and cat == "event" and "活动说明" not in b["block"]:
            continue
        dedupe = f"{cat}|{name}|{primary['start'][:10]}|{primary['end'][:10]}"
        if dedupe in seen:
            continue
        # 同名同分类已有专用帖时跳过
        if any(
            e.get("category") == cat
            and name
            and name in (e.get("header") or e.get("title") or "")
            for e in out
        ):
            continue
        seen.add(dedupe)
        for r in ranges:
            r["label"] = label_for(cat, name)
            r["category"] = cat
        remote = pick_cover_url(name, cat, cover_bank, forbid=forbid | used_urls)
        if not remote:
            remote = pick_cover_url(name, cat, cover_bank, forbid=forbid)
        if remote:
            used_urls.add(remote)
        banner = (
            cache_cover(f"ef-{cat}-{source_cid}-{name[:8]}", remote, NEWS_URL) if remote else ""
        )
        slug = re.sub(r"[^\w\u4e00-\u9fff]+", "", name)[:16] or cat
        title_map = {
            "gacha": f"「{name}」特许寻访" if "申领" not in name else f"「{name}」",
            "combat": f"「{name}」",
            "event": f"「{name}」",
        }
        if "申领" in name:
            title = f"「{name}」"
        else:
            title = title_map.get(cat, f"「{name}」")
        body = clean_body(b["block"], limit=1200)
        fuzzy = bool(primary.get("fuzzy")) or "维护前" in b["when"] or "开启后" in b["when"]
        out.append(
            build_event(
                cid=f"{source_cid}-{cat}-{slug}",
                title=title,
                header=f"「{name}」",
                banner=banner,
                link=DETAIL_URL.format(cid=source_cid),
                start=start,
                end=end,
                ranges=ranges[:4] or [primary],
                kind="preview" if start > now else "live",
                fuzzy=fuzzy,
                category=cat,
                summary=highlight_summary(b["block"], name),
                body=body,
            )
        )
        print(f"  + split [{cat}] {name} | cover={'ok' if banner else 'none'} | {out[-1]['remain']}")
    return out


def main() -> int:
    now = now_cn()
    items = fetch_list()
    events: list[dict] = []
    notes: list[str] = []
    detail_cache: dict[str, str] = {}

    maint_texts: list[str] = []
    for it in items:
        title = (it.get("title") or "").strip()
        cid = str(it.get("cid") or "")
        if re.search(r"版本预|维护|更新预告|核心章节", title):
            t = fetch_detail_text(cid)
            detail_cache[cid] = t
            maint_texts.append(t)
            maint_texts.append(title)
    next_maint = find_next_maint(maint_texts, now)
    if next_maint:
        print(f"[EF] next maint ~ {next_maint.isoformat()}")

    cover_bank = build_cover_bank(items)

    for it in items:
        title = (it.get("title") or "").strip()
        cid = str(it.get("cid") or "")
        if not cid:
            continue
        if not is_playable(title):
            notes.append(f"{cid} 跳过：{title[:40]}")
            continue

        print(f"  [detail] {cid} {title[:40]}")
        text = detail_cache.get(cid) or fetch_detail_text(cid)
        detail_cache[cid] = text
        if len(text) < 80:
            text = strip_html(it.get("brief") or "") + "\n" + text

        cover = it.get("cover") or ""
        body_full = clean_body(text)

        # 版本更新说明：拆细分卡片 + 保留总览
        if re.search(r"版本更新说明|内容说明", title):
            blocks = split_schedule_blocks(text)
            split_evs = events_from_blocks(
                blocks=blocks,
                now=now,
                next_maint=next_maint,
                cover_bank=cover_bank,
                version_cover=cover,
                source_cid=cid,
                version_title=title,
            )
            for gev in split_evs:
                gname = re.sub(r"[「」]", "", gev.get("header") or "")
                if any(
                    e.get("category") == gev.get("category")
                    and gname
                    and gname in (e.get("header") or e.get("title") or "")
                    for e in events
                ):
                    continue
                events.append(gev)

            labeled = enrich_ranges_from_blocks(blocks, now, next_maint)
            primary = pick_best_range(labeled, now) or pick_best_range(
                parse_ef_ranges(text, now, next_maint), now
            )
            if primary:
                start = datetime.fromisoformat(primary["start"])
                end = datetime.fromisoformat(primary["end"])
                if end >= now - timedelta(days=2):
                    banner = (
                        cache_cover(f"ef-{cid}", cover, "https://endfield.hypergryph.com/")
                        if cover
                        else ""
                    )
                    name = short_name(title)
                    ev = build_event(
                        cid=cid,
                        title=title,
                        header=f"「{name}」版本",
                        banner=banner,
                        link=DETAIL_URL.format(cid=cid),
                        start=start,
                        end=end,
                        ranges=labeled[:12] or [primary],
                        kind="preview" if start > now else "live",
                        fuzzy=False,
                        category="event",
                        summary=(it.get("brief") or title)[:180],
                        body=body_full,
                    )
                    if it.get("displayTime"):
                        ev["updatedAt"] = datetime.fromtimestamp(
                            int(it["displayTime"]), tz=TZ
                        ).isoformat()
                    events.append(ev)
                    print(f"  + overview [{ev['status']}] {name} · event | ranges={len(ev['allRanges'])}")
            continue

        # 寻访帖才解析「至版本维护前」；作战帖只用普通时段
        if re.search(r"寻访|卡池|申领", title):
            ranges = parse_ef_ranges(text, now, next_maint)
        else:
            ranges = parse_ranges(text, now)
        # 给时段贴更可读标签
        for r in ranges:
            lab = (r.get("label") or "").strip(" ·")
            if not lab or lab in ("活动时间", "开放时间", "· 活动时间"):
                if re.search(r"寻访|卡池|申领", title):
                    r["label"] = label_for("gacha", short_name(title))
                    r["category"] = "gacha"
                elif "机密圣所" in (r.get("raw") or "") or "机密圣所" in title:
                    r["label"] = label_for("combat", "机密圣所")
                    r["category"] = "combat"
                else:
                    r["label"] = lab or "时段"
            else:
                # 「机密圣所」开放时间 → 作战 · 机密圣所
                mq = NAMED_QUOTE.search(lab)
                if mq:
                    nm = mq.group(1)
                    cat = (
                        "combat"
                        if re.search(r"圣所|合约|丰碑|挑战", nm + title)
                        else ("gacha" if re.search(r"寻访|申领", title) else "event")
                    )
                    r["label"] = label_for(cat, nm)
                    r["category"] = cat

        primary = pick_best_range(ranges, now)

        fuzzy = False
        if not primary:
            if is_bare_announce(title) or (
                not re.search(r"寻访|卡池|申领", title) and not allow_fuzzy_estimate(title)
            ):
                notes.append(f"{cid} 纯公告无时段，跳过：{title[:40]}")
                continue
            singles = re.findall(
                r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})\s*(\d{1,2})[:：](\d{2})", text
            )
            if singles:
                y, m, d, h, mi = map(int, singles[0])
                start = datetime(y, m, d, h, mi, tzinfo=TZ)
            elif it.get("displayTime") and re.search(r"寻访|卡池|申领", title):
                start = datetime.fromtimestamp(int(it["displayTime"]), tz=TZ)
            else:
                notes.append(f"{cid} 无时段：{title[:40]}")
                continue
            if re.search(r"寻访|卡池|申领", title):
                end = next_maint or (start + timedelta(days=14))
                label = "估时（至版本维护前）" if next_maint else "估时（寻访）"
            else:
                end = start + timedelta(days=14)
                label = "估时（活动）"
            primary = {
                "label": label,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "raw": "single-node",
            }
            ranges = [primary]
            fuzzy = True

        start = datetime.fromisoformat(primary["start"])
        end = datetime.fromisoformat(primary["end"])
        if end < now - timedelta(days=2):
            notes.append(f"{cid} 已过期：{title[:40]}")
            continue

        banner = cache_cover(f"ef-{cid}", cover, "https://endfield.hypergryph.com/") if cover else ""
        name = short_name(title)
        cat = (
            "gacha"
            if re.search(r"寻访|卡池|申领", title)
            else ("event" if re.search(r"签到|特卖|申领|预下载|版本更新", title) else "combat")
        )
        # 专用寻访帖与版本拆条去重（同名保留专用帖）
        if cat == "gacha":
            events = [
                e
                for e in events
                if not (
                    e.get("category") == "gacha"
                    and name in (e.get("header") or e.get("title") or "")
                )
            ]
        ev = build_event(
            cid=cid,
            title=title,
            header=f"「{name}」",
            banner=banner,
            link=DETAIL_URL.format(cid=cid),
            start=start,
            end=end,
            ranges=ranges,
            kind="preview" if start > now else "live",
            fuzzy=fuzzy,
            category=cat,
            summary=(it.get("brief") or "")[:180],
            body=body_full,
        )
        if it.get("displayTime"):
            ev["updatedAt"] = datetime.fromtimestamp(int(it["displayTime"]), tz=TZ).isoformat()
        events.append(ev)
        print(f"  + [{ev['status']}] {name} · {cat} | {ev['remain']}")

    rank = {"进行中": 0, "即将开始": 1, "已结束": 2}
    cat_rank = {"gacha": 0, "combat": 1, "event": 2, "web": 3}
    events.sort(
        key=lambda e: (
            cat_rank.get(e.get("category") or "", 9),
            rank.get(e["status"], 9),
            e.get("start") or "",
        )
    )

    payload = {
        "game": "终末地",
        "source": NEWS_URL,
        "fetchedAt": now.isoformat(),
        "timezone": "Asia/Shanghai",
        "count": len(events),
        "notes": notes[:40],
        "events": events,
    }
    if next_maint:
        payload["notes"] = [f"下次版本维护估：{next_maint.isoformat()}"] + payload["notes"]
    write_events(DATA / "endfield.json", payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
