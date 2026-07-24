#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 data/ 同步到 public/data/，供静态站点（GitHub Pages 等）直接读。"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data"
DST = ROOT / "public" / "data"

# 不同步到站点的文件（审计/抓取摘要仅留 data/）
SKIP = {
    "cache",
    "_probe_bl.json",
    "sample_details.json",
    "audit-report.json",
    "fetch-summary.json",
}


def main() -> int:
    DST.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in sorted(SRC.glob("*.json")):
        if src.name in SKIP or src.name.startswith("_"):
            continue
        dest = DST / src.name
        shutil.copy2(src, dest)
        copied += 1
        print(f"  [pub] {src.name}")

    # 兼容：方舟主数据同时叫 events.json（已复制）
    meta = DST / "games-meta.json"
    if not meta.exists() and (SRC / "games-meta.json").exists():
        shutil.copy2(SRC / "games-meta.json", meta)

    print(f"[ok] 已发布 {copied} 个 JSON → public/data/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
