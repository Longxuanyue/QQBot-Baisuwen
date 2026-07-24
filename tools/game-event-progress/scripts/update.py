#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键更新流水线（抓取 → 自查 → 发布到 public/data → 写 status）。

用法:
  python scripts/update.py
  python scripts/update.py --jobs 3
  python scripts/update.py --skip-fetch   # 只审计+发布
  python scripts/update.py --strict      # 软警告也失败
  python scripts/update.py --dry-run     # 只抓不写
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
DATA = PROJECT / "data"


def run_py(script: str, extra: list[str] | None = None) -> int:
    cmd = [sys.executable, str(ROOT / script), *(extra or [])]
    print(f"\n>>> {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=str(PROJECT))


def write_status(*, fetch_ok: bool, audit_hard: int, audit_soft: int, seconds: float) -> None:
    from common import now_cn  # noqa: WPS433

    status = {
        "site": "活动进度",
        "updatedAt": now_cn().isoformat(),
        "timezone": "Asia/Shanghai",
        "fetchOk": fetch_ok,
        "auditHard": audit_hard,
        "auditSoft": audit_soft,
        "durationSec": round(seconds, 1),
        "message": "数据已刷新" if fetch_ok and audit_hard == 0 else "部分失败，见 audit-report",
    }
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # 同步到 public
    pub = PROJECT / "public" / "data"
    pub.mkdir(parents=True, exist_ok=True)
    (pub / "status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[status] {status['updatedAt']} · {status['message']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="活动进度一键更新")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--skip-audit", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--only", type=str, default="")
    ap.add_argument("--dry-run", action="store_true", help="抓取+审计，不写盘/不发布")
    args = ap.parse_args()

    t0 = time.time()
    fetch_ok = True

    if not args.skip_fetch:
        extra = [f"--jobs={args.jobs}", f"--timeout={args.timeout}"]
        if args.only:
            extra.append(f"--only={args.only}")
        if args.dry_run:
            extra.append("--dry-run")
        code = run_py("fetch_all.py", extra)
        fetch_ok = code == 0
        if not fetch_ok:
            print("[warn] 部分抓取失败，继续审计与发布已有数据")

    audit_hard = 0
    audit_soft = 0
    if not args.skip_audit:
        code = run_py("audit.py", ["--strict"] if args.strict else [])
        report_path = DATA / "audit-report.json"
        if report_path.exists():
            rep = json.loads(report_path.read_text(encoding="utf-8"))
            audit_hard = int(rep.get("hard") or 0)
            audit_soft = int(rep.get("soft") or 0)
        if code == 2:
            print("[warn] 存在硬问题，仍发布当前数据供排查")
        elif code == 1 and args.strict:
            print("[warn] 严格模式：存在软警告")

    if args.dry_run:
        print("[dry-run] 跳过 publish / status")
        print(f"[done] {time.time() - t0:.1f}s · dry-run")
        return 0 if fetch_ok and audit_hard == 0 else 1

    pub_code = run_py("publish_data.py")
    write_status(
        fetch_ok=fetch_ok,
        audit_hard=audit_hard,
        audit_soft=audit_soft,
        seconds=time.time() - t0,
    )

    # 硬问题或发布失败 → 非 0（CI 可据此告警；本地仍已写出数据）
    if pub_code != 0:
        return pub_code
    if audit_hard > 0:
        return 2
    if not fetch_ok:
        return 1
    print(f"\n[ok] 更新完成 · {round(time.time() - t0, 1)}s")
    return 0


if __name__ == "__main__":
    # 保证可 import common
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
