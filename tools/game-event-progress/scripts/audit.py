#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据自查：写报告 + 退出码（供 CI / update 流水线）。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, is_bare_announce, now_cn  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data" / "audit-report.json"
PUBLIC_DATA = ROOT / "public" / "data"
# 起止漂移超过该阈值记软警告
DRIFT_HOURS = 48


def audit(data_dir: Path | None = None) -> dict:
    data_dir = data_dir or DATA
    issues: list[dict] = []
    summary: list[dict] = []
    lines = ["=== SUMMARY ==="]

    for p in sorted(data_dir.glob("*.json")):
        if p.name in (
            "games-meta.json",
            "status.json",
            "audit-report.json",
            "fetch-summary.json",
        ):
            continue
        if p.name.startswith("_"):
            continue
        if p.name.endswith("-summary.json"):
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception as e:
            issues.append({"game": p.name, "code": "JSON_FAIL", "detail": str(e)})
            continue
        if not isinstance(d, dict):
            issues.append({"game": p.stem, "code": "NOT_DICT", "detail": type(d).__name__})
            continue

        evs = d.get("events") or []
        pending = d.get("pending")
        titles = [e.get("title") or "" for e in evs]
        dups = [(t, n) for t, n in Counter(titles).items() if t and n > 1]
        bare_sched: list[str] = []
        fuzzy_ann: list[str] = []
        empty_banner = 0
        http_banner = 0
        cats: Counter = Counter()
        for e in evs:
            t = e.get("title") or ""
            cats[e.get("category") or "?"] += 1
            b = e.get("banner") or ""
            if not b:
                empty_banner += 1
            if b.startswith("http://"):
                http_banner += 1
            if is_bare_announce(t) and e.get("hasSchedule"):
                bare_sched.append(t[:48])
            if e.get("fuzzy") and is_bare_announce(t):
                fuzzy_ann.append(t[:48])

        row = {
            "game": p.stem,
            "count": len(evs),
            "pending": pending,
            "cats": dict(cats),
            "emptyBanner": empty_banner,
            "dups": len(dups),
            "bare": len(bare_sched),
        }
        summary.append(row)
        lines.append(
            f"{p.stem:14} n={len(evs):3} pend={pending!s:5} cats={dict(cats)} "
            f"emptyBan={empty_banner} bare={len(bare_sched)} dups={len(dups)} http={http_banner}"
        )

        if dups:
            issues.append({"game": p.stem, "code": "DUP_TITLE", "detail": dups[:4]})
        if bare_sched:
            issues.append(
                {"game": p.stem, "code": "BARE_ANNOUNCE_SCHEDULED", "detail": bare_sched[:6]}
            )
        if fuzzy_ann:
            issues.append({"game": p.stem, "code": "FUZZY_ANNOUNCE", "detail": fuzzy_ann[:6]})
        if http_banner:
            issues.append({"game": p.stem, "code": "HTTP_BANNER", "detail": http_banner})
        if pending and len(evs) == 0:
            # 空 pending 记为软警告，不阻断发布（源站可能暂时无活动）
            issues.append({"game": p.stem, "code": "PENDING_EMPTY", "detail": "", "soft": True})
        if not pending and len(evs) == 0:
            issues.append({"game": p.stem, "code": "EMPTY_NOT_PENDING", "detail": ""})

        gacha_need = {
            "genshin",
            "zzz",
            "wuwa",
            "bluearchive",
            "endfield",
            "events",
        }
        if p.stem in gacha_need and cats.get("gacha", 0) == 0 and len(evs) > 0:
            issues.append(
                {"game": p.stem, "code": "NO_GACHA", "detail": f"events={len(evs)}", "soft": True}
            )

        # 与上一份已发布数据比漂移（同 id）
        prev_path = PUBLIC_DATA / p.name
        if prev_path.exists() and evs:
            try:
                prev = json.loads(prev_path.read_text(encoding="utf-8-sig"))
                prev_map = {
                    str(e.get("id")): e
                    for e in (prev.get("events") or [])
                    if e.get("id")
                }
                drifted = []
                for e in evs:
                    eid = str(e.get("id") or "")
                    old = prev_map.get(eid)
                    if not old or not e.get("start") or not old.get("start"):
                        continue
                    try:
                        ds = abs(
                            datetime.fromisoformat(str(e["start"]))
                            - datetime.fromisoformat(str(old["start"]))
                        )
                        de = abs(
                            datetime.fromisoformat(str(e["end"]))
                            - datetime.fromisoformat(str(old["end"]))
                        ) if e.get("end") and old.get("end") else timedelta(0)
                    except Exception:
                        continue
                    if ds > timedelta(hours=DRIFT_HOURS) or de > timedelta(hours=DRIFT_HOURS):
                        drifted.append(
                            f"{(e.get('header') or e.get('title') or eid)[:24]} "
                            f"Δstart={ds.total_seconds()/3600:.0f}h"
                        )
                if drifted:
                    issues.append(
                        {
                            "game": p.stem,
                            "code": "SCHEDULE_DRIFT",
                            "detail": drifted[:6],
                            "soft": True,
                        }
                    )
            except Exception:
                pass

    # Wiki 元数据
    meta_path = data_dir / "games-meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        games = meta.get("games") or {}
        builtin = [
            "arknights",
            "endfield",
            "bluearchive",
            "genshin",
            "starrail",
            "zzz",
            "wuwa",
            "azurlane",
            "nikke",
            "reverse1999",
            "ptn",
            "snowbreak",
            "gfl2",
            "hearthstone",
            "pvz2",
            "naraka",
            "delta",
        ]
        for gid in builtin:
            if gid not in games:
                issues.append({"game": gid, "code": "META_MISSING", "detail": ""})
            elif not ((games[gid].get("wiki") or {}).get("url")):
                issues.append({"game": gid, "code": "NO_WIKI", "detail": "", "soft": True})

    hard = [i for i in issues if not i.get("soft")]
    soft = [i for i in issues if i.get("soft")]
    lines.append("=== ISSUES (hard) ===")
    for i in hard:
        lines.append(f"{i['game']} | {i['code']} | {i.get('detail')}")
    lines.append("=== ISSUES (soft) ===")
    for i in soft:
        lines.append(f"{i['game']} | {i['code']} | {i.get('detail')}")
    lines.append(f"hard={len(hard)} soft={len(soft)}")

    report = {
        "fetchedAt": now_cn().isoformat(),
        "hard": len(hard),
        "soft": len(soft),
        "issues": issues,
        "summary": summary,
        "text": "\n".join(lines),
    }
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="活动数据自查")
    ap.add_argument("--strict", action="store_true", help="软警告也失败")
    ap.add_argument("--json", action="store_true", help="只输出 JSON")
    args = ap.parse_args()

    report = audit()
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "scripts" / "_audit_out.txt").write_text(report["text"], encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(report["text"])
        print(f"\n[ok] 报告 → {REPORT}")

    if report["hard"] > 0:
        return 2
    if args.strict and report["soft"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
