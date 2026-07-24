#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""依次/并行刷新全部已接入游戏数据（单脚本失败不中断整批）。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent

SCRIPTS = [
    "fetch_arknights.py",
    "fetch_bluearchive.py",
    "fetch_endfield.py",
    "fetch_hoyoverse.py",
    "fetch_wuwa.py",
    "fetch_azurlane.py",
    "fetch_more.py",
]


def run_one(script: str, timeout: int) -> dict:
    t0 = time.time()
    env = os.environ.copy()
    try:
        r = subprocess.run(
            [sys.executable, str(ROOT / script)],
            cwd=str(PROJECT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
        out = (r.stdout or "")[-4000:]
        err = (r.stderr or "")[-2000:]
        return {
            "script": script,
            "ok": r.returncode == 0,
            "code": r.returncode,
            "seconds": round(time.time() - t0, 1),
            "tail": out[-800:] if out else err[-800:],
        }
    except subprocess.TimeoutExpired:
        return {
            "script": script,
            "ok": False,
            "code": -9,
            "seconds": timeout,
            "tail": f"TIMEOUT >{timeout}s",
        }
    except Exception as e:
        return {
            "script": script,
            "ok": False,
            "code": -1,
            "seconds": round(time.time() - t0, 1),
            "tail": str(e),
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=1, help="并行数（默认串行更稳）")
    ap.add_argument("--timeout", type=int, default=240, help="单脚本超时秒")
    ap.add_argument("--only", type=str, default="", help="逗号分隔脚本名过滤")
    ap.add_argument("--dry-run", action="store_true", help="只抓取校验，不写 data/*.json")
    args = ap.parse_args()

    if args.dry_run:
        os.environ["GEP_DRY_RUN"] = "1"
        print("[fetch_all] DRY_RUN：不写入 data/")

    scripts = SCRIPTS
    if args.only:
        want = {s.strip() for s in args.only.split(",") if s.strip()}
        scripts = [s for s in SCRIPTS if s in want or Path(s).stem in want]
        if not scripts:
            print("[err] --only 无匹配")
            return 1

    results: list[dict] = []
    jobs = max(1, min(args.jobs, len(scripts)))

    if jobs == 1:
        for s in scripts:
            print(f"\n===== {s} =====")
            row = run_one(s, args.timeout)
            results.append(row)
            print(row["tail"][-500:] if row["tail"] else "")
            print(f"[{'ok' if row['ok'] else 'FAIL'}] {s} {row['seconds']}s")
    else:
        print(f"[fetch_all] parallel jobs={jobs}")
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            futs = {ex.submit(run_one, s, args.timeout): s for s in scripts}
            for fut in as_completed(futs):
                row = fut.result()
                results.append(row)
                mark = "ok" if row["ok"] else "FAIL"
                print(f"[{mark}] {row['script']} {row['seconds']}s")

    results.sort(key=lambda r: scripts.index(r["script"]) if r["script"] in scripts else 99)
    failed = [r for r in results if not r["ok"]]
    summary = {
        "ok": len(failed) == 0,
        "total": len(results),
        "failed": [r["script"] for r in failed],
        "results": results,
    }
    out = PROJECT / "data" / "fetch-summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[summary] {len(results) - len(failed)}/{len(results)} ok → {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
