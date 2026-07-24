#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 App Store 搜索并保存游戏图标。"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image

OUT = Path(__file__).resolve().parents[1] / "public" / "icons"
UA = {"User-Agent": "Mozilla/5.0"}

# 与 app.js BUILTIN_GAMES 对齐：每个游戏都要有图标
GAMES = [
    ("arknights", "明日方舟", ["明日方舟"]),
    ("endfield", "终末地", ["终末地", "明日方舟：终末地"]),
    ("bluearchive", "蔚蓝档案", ["蔚蓝档案", "碧蓝档案"]),
    ("genshin", "原神", ["原神"]),
    ("starrail", "崩坏：星穹铁道", ["星穹铁道", "崩坏：星穹铁道"]),
    ("zzz", "绝区零", ["绝区零"]),
    ("wuwa", "鸣潮", ["鸣潮"]),
    ("azurlane", "碧蓝航线", ["碧蓝航线"]),
    ("nikke", "胜利女神：NIKKE", ["NIKKE", "胜利女神"]),
    ("reverse1999", "重返未来：1999", ["重返未来：1999", "1999"]),
    ("ptn", "无期迷途", ["无期迷途"]),
    ("snowbreak", "尘白禁区", ["尘白禁区"]),
    ("gfl2", "少女前线2：追放", ["少女前线2", "少女前线２"]),
    ("hearthstone", "炉石传说", ["炉石传说", "Hearthstone"]),
    ("pvz2", "植物大战僵尸2", ["植物大战僵尸2", "植物大战僵尸"]),
    ("naraka", "永劫无间", ["永劫无间"]),
    ("delta", "三角洲行动", ["三角洲行动", "Delta Force"]),
]


def search(term: str) -> dict | None:
    q = urllib.parse.quote(term)
    url = f"https://itunes.apple.com/search?term={q}&country=cn&entity=software&limit=8"
    req = urllib.request.Request(url, headers=UA)
    data = json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
    results = data.get("results") or []
    return results


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for stem, prefer, keywords in GAMES:
        found = None
        for kw in keywords:
            try:
                results = search(kw)
            except Exception as e:
                print("search fail", stem, kw, e)
                continue
            for r in results:
                name = r.get("trackName") or ""
                if any(k in name for k in keywords) or prefer in name:
                    found = r
                    break
            if found:
                break
        if not found:
            print("miss", stem)
            continue
        print(stem, found.get("trackName"), found.get("trackId"))
        url = (found.get("artworkUrl512") or found.get("artworkUrl100") or "").replace(
            "512x512bb", "256x256bb"
        )
        img = urllib.request.urlopen(
            urllib.request.Request(url, headers=UA), timeout=25
        ).read()
        Image.open(BytesIO(img)).convert("RGBA").resize(
            (128, 128), Image.Resampling.LANCZOS
        ).save(OUT / f"{stem}.png")
        print("  saved")


if __name__ == "__main__":
    main()
