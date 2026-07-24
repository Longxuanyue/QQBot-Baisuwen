#!/usr/bin/env bash
# cron 示例：0 */6 * * * cd /path/to/repo && ./scripts/run_update.sh >> data/cron.log 2>&1
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p data
python3 scripts/update.py --jobs 1 --timeout 300
