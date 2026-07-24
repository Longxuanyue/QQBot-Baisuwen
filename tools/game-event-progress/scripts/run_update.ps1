# 本地定时刷新：可用「任务计划程序」每 6 小时运行本脚本
# 示例：powershell -ExecutionPolicy Bypass -File scripts\run_update.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$logDir = Join-Path $Root "data"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("update-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")

Write-Host "[update] $Root"
& python scripts/update.py --jobs 1 --timeout 300 *>&1 | Tee-Object -FilePath $log
$code = $LASTEXITCODE
Write-Host "[update] exit=$code log=$log"
exit $code
