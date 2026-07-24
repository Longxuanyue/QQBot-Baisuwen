# 活动进度

**作用**：把多游戏正在进行的作战 / 卡池 / 网页活动，汇总成一张可静态部署的进度页。

**原理**：抓各游戏官方公告或公开日历 → 用规则解析起止时间 → 缓存封面 → 写成 JSON → 前端按游戏分行展示进度条。

**工作流**：`scripts/update.py` 一键跑完「抓取 → 自查 → 发布到 `public/data` → 写更新时间」；GitHub Actions 定时执行同一流水线。

本地预览：`http://localhost:5173/public/`

---

## 快速开始

```bash
# 抓取 + 自查 + 发布到 public/data
python scripts/update.py

# 本地预览（项目根目录）
python -m http.server 5173
```

浏览器打开：http://localhost:5173/public/

---

## 首次运行须知

仓库**不包含**运行时可通过脚本自动获取的资源，以减小仓库体积。clone 后首次运行需按顺序执行：

### 1. 生成游戏图标（仅首次）

```bash
python scripts/fetch_icons.py
```

从 App Store 搜索并下载 17 款游戏的图标，缩放为 128×128 PNG 存入 `public/icons/`。

### 2. 抓取数据 + 封面图

```bash
python scripts/update.py
```

流水线会自动完成：

| 步骤 | 产出 | 说明 |
|------|------|------|
| `fetch_all.py` | `data/*.json` + `public/covers/*` | 抓取各游戏公告，下载封面图缓存到本地 |
| `audit.py` | `data/audit-report.json` | 数据质量自查 |
| `publish_data.py` | `public/data/*.json` | 同步 JSON 到前端可读路径 |

> **注意**：首次运行 `update.py` 需要从 17+ 款游戏的外部源（官方 API、CDN、Wiki）下载全部封面图，耗时会比后续增量更新长很多，请确保网络畅通。

### 版本控制说明

以下目录/文件已加入 `.gitignore`，不会推送到仓库：

| 目录 | 体积 | 生成方式 |
|------|------|----------|
| `data/` | ~几 MB | `update.py` 自动生成 |
| `public/data/` | ~几 MB | `publish_data.py` 同步生成 |
| `public/covers/` | ~200 MB | `fetch_*.py` 从源站下载 |
| `public/icons/*.png` | ~600 KB | `fetch_icons.py` 从 App Store 下载 |

`public/icons/custom.svg`（自定义游戏占位图标）为手动维护的静态资源，保留在仓库中。

---

## 日常运维（上线后必做）

### 一键更新（推荐）

```bash
python scripts/update.py
```

流水线顺序：

1. `fetch_all.py` — 抓取各游戏（单源失败不阻断）
2. `audit.py` — 自查，写 `data/audit-report.json`
3. `publish_data.py` — 同步 JSON → `public/data/`（静态站可读）
4. 写 `data/status.json` + `public/data/status.json`（前端显示「更新于」）

常用参数：

| 参数 | 说明 |
|------|------|
| `--jobs 2` | 并行抓取（不稳时用 1） |
| `--timeout 300` | 单脚本超时秒 |
| `--skip-fetch` | 只审计 + 发布 |
| `--strict` | 软警告也失败 |
| `--only fetch_hoyoverse.py` | 只跑部分脚本 |

### 自动定时

**GitHub Actions（推荐）**

1. 把仓库推到 GitHub，默认分支 `main` 或 `master`
2. 已带 [`.github/workflows/update.yml`](.github/workflows/update.yml)：每 6 小时抓取并自动 commit 数据
3. GitHub Pages：Settings → Pages → 源选 `Deploy from branch`，目录 `/public`（或用 Actions 部署 `public`）

**Windows 任务计划**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_update.ps1
```

建议每 6 小时运行一次。

**Linux cron**

```cron
0 */6 * * * cd /path/to/repo && ./scripts/run_update.sh >> data/cron.log 2>&1
```

---

## 目录

| 路径 | 用途 |
|------|------|
| `public/` | 静态站点（HTML/CSS/JS + covers + data） |
| `data/` | 抓取原始 JSON / 审计报告 |
| `scripts/update.py` | 一键流水线 |
| `scripts/fetch_*.py` | 各游戏抓取 |
| `scripts/audit.py` | 自查 |
| `scripts/publish_data.py` | 发布到 `public/data` |

前端数据路径优先 `./data/`（已发布），找不到再回退 `../data/`。

---

## 自查

```bash
python scripts/audit.py
python scripts/audit.py --strict   # CI 用
```

- 退出码 `2`：硬问题（重复标题、纯公告带时段等）
- 退出码 `1`：仅 `--strict` 时的软警告（空 pending、缺 Wiki 等）
- 报告：`data/audit-report.json`

---

## 部署检查清单

- [ ] `python scripts/update.py` 成功
- [ ] 打开 `/public/` 能看到「数据更新于 …」
- [ ] 游戏选择 / 排序 / 搜索可用
- [ ] GitHub Actions 已启用（或本机定时任务）
- [ ] Pages / CDN 指向 `public/`

---

## 数据来源说明

各游戏官方公告 API / 官网新闻 / 公开日历（如星铁跃迁日历）。估时条目会标「估时」，请以游戏内为准。
