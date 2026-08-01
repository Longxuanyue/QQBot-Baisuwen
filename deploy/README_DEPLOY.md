# 白苏文 (BaiSuWen) 部署指南

本指南用于从零部署白苏文 QQ 智能伴侣机器人。

---

## 目录

- [硬件要求](#硬件要求)
- [前置依赖](#前置依赖)
- [快速开始（一键部署）](#快速开始一键部署)
- [手动部署](#手动部署)
- [配置说明](#配置说明)
- [启动与运维](#启动与运维)
- [TTS 引擎配置](#tts-引擎配置)
- [常见问题](#常见问题)

---

## 硬件要求

| 组件 | 最低配置 | 推荐配置 |
|------|----------|----------|
| CPU | 4 核 | 8 核以上 |
| 内存 | 8 GB | 16 GB 以上 |
| 磁盘 | 10 GB | 50 GB (SSD) |
| GPU | 无（CPU 推理） | NVIDIA 显卡 8GB+ 显存 |

> **说明**：ASR (Whisper) 和 TTS 推理可使用 CPU，但 GPU 能显著提速。
> 纯对话功能（LLM + 记忆）无 GPU 需求。

---

## 前置依赖

在部署白苏文之前，你需要准备：

### 1. Python 3.10+

- **Windows**: [python.org](https://www.python.org/downloads/) 下载安装包，**安装时勾选「Add Python to PATH」**
- **Ubuntu/Debian**: `sudo apt install python3.12 python3.12-venv`
- **macOS**: `brew install python@3.12`

### 2. DeepSeek API Key

1. 访问 [platform.deepseek.com](https://platform.deepseek.com)
2. 注册/登录，进入「API Keys」页面
3. 创建一个新的 API Key 并复制保存

### 3. QQ 协议端（三选一）

白苏文基于 NoneBot2 + OneBot V11 协议，需要一个 QQ 协议端对接：

| 协议端 | 说明 | 推荐度 |
|--------|------|--------|
| [NapCat](https://github.com/NapNeko/NapCatQQ) | 基于 NTQQ，Windows 首选 | ⭐⭐⭐ |
| [Lagrange](https://github.com/LagrangeDev/Lagrange.Core) | 跨平台，轻量 | ⭐⭐ |
| [LLOneBot](https://github.com/LLOneBot/LLOneBot) | 基于 QQNT LiteLoader | ⭐ |

配置协议端反向 WebSocket 为: `ws://127.0.0.1:42200/onebot/v11/ws`

### 4. （可选）GPT-SoVITS 模型

若使用 GPT-SoVITS TTS 引擎（默认使用 VITS），需额外下载模型文件到 `D:/GPT-SoVITS-main`，详见 [TTS 引擎配置](#tts-引擎配置)。

---

## 快速开始（一键部署）

### Windows

```batch
:: 克隆仓库
git clone https://github.com/<你的用户名>/baisuwen.git
cd baisuwen

:: 双击运行
deploy\deploy.bat
```

或直接在命令行中：

```batch
python deploy\deploy.py
```

### Linux / macOS

```bash
git clone https://github.com/<你的用户名>/baisuwen.git
cd baisuwen
bash deploy/deploy.sh
```

### 部署流程概览

部署脚本会依次执行：

1. **环境检测** — 验证 Python >= 3.10
2. **虚拟环境** — 在 `baisuwen/../nonebot/` 下创建 Python venv
3. **依赖安装** — 安装所有 Python 依赖（含 PyTorch、Whisper，约 5~10 分钟）
4. **配置引导** — 交互式填写 API Key、QQ 号、TTS 引擎等
5. **目录初始化** — 创建 `user_data/`、`data/` 等运行时目录

---

## 手动部署

如果你更希望手动控制每一步：

```bash
# 1. 创建虚拟环境
python -m venv ../nonebot       # Windows
python3 -m venv ../nonebot       # Linux/macOS

# 2. 激活虚拟环境
..\nonebot\Scripts\activate      # Windows (cmd)
source ../nonebot/bin/activate   # Linux/macOS

# 3. 安装 nb-cli
pip install nb-cli>=0.7.0

# 4. 安装依赖
pip install -r requirements.txt

# 5. 创建配置文件
copy .env.example .env           # Windows
cp .env.example .env             # Linux/macOS

# 6. 编辑 .env 文件，填入必填参数（见下方配置说明）

# 7. 启动
nb run
```

---

## 配置说明

部署后，所有配置集中在项目根目录的 `.env` 文件中。以下是关键配置项：

### 必填项

| 配置项 | 说明 | 示例 |
|--------|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | `sk-xxxxxxxx` |
| `SUPERUSERS` | 超级用户 QQ 号（JSON 数组） | `["2461292801"]` |

### 常用配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `PORT` | NoneBot 监听端口 | `42200` |
| `BOT_NICKNAME` | 机器人昵称 | `小玖` |
| `NICKNAME` | to_me 检测昵称（JSON 数组） | `["小玖"]` |
| `LOG_LEVEL` | 日志级别 | `INFO` |
| `ENABLE_ASR` | 是否启用语音识别 | `true` |
| `ASR_MODEL_SIZE` | ASR 模型大小 | `small` |
| `ENABLE_TTS` | 是否启用语音合成 | `true` |
| `TTS_ENGINE` | TTS 引擎 (`vits` / `gpt_sovits`) | `vits` |
| `ENABLE_MULTIMODAL` | 是否启用图片理解 | `true` |
| `BOT_SLEEP_START` | 休眠开始时间 | `23:30` |
| `BOT_SLEEP_END` | 休眠结束时间 | `06:00` |
| `MEMORY_TOP_K` | 每次检索的记忆条数 | `5` |

### 完整配置项

参见 [`.env.example`](../.env.example) 中的注释说明。

---

## 启动与运维

### 启动

**推荐方式** — 双击 `start_bot.bat`（Windows）：

- 自动激活虚拟环境、启动 Bot
- 内置「看门狗」：Bot 异常退出时自动重启
- 退出码 `42` 表示 WebUI 请求重启 → 自动重启
- 其他退出码 → 彻底退出

**手动方式**：

```bash
..\nonebot\Scripts\activate    # Windows
source ../nonebot/bin/activate  # Linux/macOS
nb run
```

### 停止

- 在 Bot 运行的终端按 `Ctrl+C`
- 或通过 WebUI → 系统管理 → 关闭服务

### Web 管理后台

启动后浏览器访问: **http://127.0.0.1:42200/webui/**

首次登录：在 QQ 中向 Bot 发送 `/auth <token>`（token 在 WebUI 登录页显示）

功能包括：
- 📊 仪表盘 — 运行状态总览
- 🔌 插件管理 — 启用/禁用插件
- ⚙️ 配置编辑 — 在线修改 .env
- 🧠 记忆浏览 — 查看/清理用户记忆
- 👤 人设编辑 — 调整 Bot 性格
- 📝 审计日志 — 操作记录
- 💾 备份恢复 — 数据导入导出

### 更新

```bash
git pull
..\nonebot\Scripts\activate
pip install -r requirements.txt --upgrade
nb run
```

---

## TTS 引擎配置

### 方式一：VITS 引擎（默认，推荐）

无需额外配置，已内嵌在插件中。模型文件放在 `models/` 目录：

```
models/
├── G_latest.pth              # VITS 模型权重 (约 158 MB)
└── finetune_speaker.json     # 说话人配置
```

### 方式二：GPT-SoVITS 引擎

步骤：

1. **克隆 GPT-SoVITS 仓库到 `D:\GPT-SoVITS-main`**

```bash
git clone https://github.com/RVC-Boss/GPT-SoVITS.git D:\GPT-SoVITS-main
cd D:\GPT-SoVITS-main
pip install -r requirements.txt
```

2. **下载预训练模型**

参照 GPT-SoVITS 官方文档下载相应版本的预训练权重。

3. **准备参考音频**

将角色参考音频（`.wav`）放入 `ref_audio/` 目录，运行索引构建：

```bash
python ref_audio/build_index.py
```

4. **修改 `.env` 配置**

```ini
TTS_ENGINE=gpt_sovits
GPT_SOVITS_CONFIG=D:/GPT-SoVITS-main/GPT_SoVITS/configs/tts_infer.yaml
GPT_SOVITS_VERSION=v2ProPlus
GPT_SOVITS_DEFAULT_CHARACTER=陈千语
```

---

## 常见问题

### Q: 部署时提示 "Python 版本过低"

**A**: 白苏文需要 Python >= 3.10。请从 [python.org](https://www.python.org/downloads/) 安装最新版。

### Q: 启动后 QQ 收不到消息

**A**: 检查：
1. QQ 协议端（NapCat 等）是否在运行
2. 协议端 WebSocket 地址是否配置为 `ws://127.0.0.1:42200/onebot/v11/ws`
3. `.env` 中 `PORT` 是否与协议端端口一致

### Q: ASR 模型下载很慢

**A**: Whisper 模型首次运行时会从 HuggingFace 下载（约 500MB~1.5GB）。可以手动下载后放入缓存目录，或设置镜像：

```ini
# 设置 HuggingFace 镜像（国内）
HF_ENDPOINT=https://hf-mirror.com
```

### Q: CUDA Out of Memory

**A**: 显存不足时尝试：
```ini
ASR_DEVICE=cpu
TTS_DEVICE=cpu
```

### Q: 如何更换 LLM 后端

**A**: 白苏文默认使用 DeepSeek API（OpenAI 兼容格式）。要更换其他 LLM，修改 `.env`：

```ini
DEEPSEEK_API_BASE=https://your-api-endpoint/v1
DEEPSEEK_MODEL=your-model-name
```

任何 OpenAI 兼容的 API 端点都可以直接使用。

### Q: 如何备份数据

**A**: 使用 WebUI → 备份恢复，或手动备份以下目录：
```
user_data/    # 用户记忆数据库
data/         # 配置备份、审计日志
models/       # TTS 模型
```

---

## 项目结构

```
baisuwen/
├── deploy/                  ← 📦 部署工具（本目录）
│   ├── deploy.py            # 部署主脚本
│   ├── deploy.bat           # Windows 入口
│   ├── deploy.sh            # Linux/macOS 入口
│   └── README_DEPLOY.md     # 本文件
├── src/plugins/             # 插件目录（13 个插件）
├── models/                  # TTS 模型文件
├── ref_audio/               # GPT-SoVITS 参考音频
├── user_data/               # 用户记忆数据库
├── data/                    # 配置备份 / 审计日志
├── start_bot.bat            # 看门狗启动脚本
├── .env                     # 运行时配置
├── .env.example             # 配置模板
├── requirements.txt         # Python 依赖清单
└── pyproject.toml           # 项目元数据
```

---

> 🤖 部署过程中遇到问题？欢迎提交 Issue。
