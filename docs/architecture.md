# 架构说明

本文档描述白苏文（BaiSuWen）的整体架构与核心模块设计，帮助理解项目如何工作以及如何在此基础上扩展。

## 一、技术栈

| 层 | 技术 |
|----|------|
| 机器人框架 | [NoneBot2](https://github.com/nonebot/nonebot2)（FastAPI + WebSocket 驱动） |
| 协议 | OneBot V11（NapCat / Lagrange / LLOneBot 等反向 WS 接入） |
| 对话模型 | DeepSeek API（OpenAI 兼容协议，可替换） |
| 记忆存储 | SQLite（WAL 模式）+ FTS5 全文检索 + jieba 分词 |
| 语音识别 | OpenAI Whisper（本地推理） |
| 语音合成 | VITS（内置）或 GPT-SoVITS（外部项目） |
| 图片理解 | LLM Vision API（OpenAI 兼容） |
| WebUI | FastAPI 子应用（Jinja2 模板 + WebSocket） |
| 定时任务 | nonebot-plugin-apscheduler |

## 二、目录结构

```
baisuwen/
├── src/plugins/
│   ├── nonebot_plugin_update_baisuwen/  # 核心插件：对话编排、LLM、人设、语音开关
│   ├── nonebot_plugin_memory/           # 记忆系统（遗忘曲线、检索、升级、合并）
│   ├── nonebot_plugin_dialog/           # 多轮对话会话管理
│   ├── nonebot_plugin_tts/              # TTS（VITS 内置 + GPT-SoVITS 引擎 + 情感角色路由）
│   ├── nonebot_plugin_asr/              # Whisper 语音识别
│   ├── nonebot_plugin_multimodal/       # 图片理解（SSRF 防护下载 + LLM Vision）
│   ├── nonebot_plugin_sentiment/        # 情感分析（规则/LLM 双模式）
│   ├── nonebot_plugin_profile/          # 用户画像（记忆库规则提取）
│   ├── nonebot_plugin_webui/            # Web 管理后台（认证/审计/备份/重启）
│   ├── nonebot_plugin_admin/            # QQ 端管理命令
│   ├── nonebot_plugin_gamenews/         # 游戏新闻推送（对接 tools/game-event-progress）
│   ├── nonebot_plugin_strongholdtools/  # 明日方舟-卫戍协议敌人查询
│   └── nonebot_plugin_help/             # 帮助信息收集
├── tools/
│   ├── game-event-progress/             # 独立数据爬取工具（gamenews 的数据源）
│   ├── memory_cli.py                    # 记忆管理 CLI
│   └── view_memory.py                   # 记忆查看 CLI
├── deploy/                              # 一键部署脚本（deploy.py / .bat / .sh）
├── models/                              # VITS 模型权重（Releases 分发，不入库）
├── ref_audio/                           # GPT-SoVITS 参考音频（不入库）
├── user_data/                           # 每用户记忆库（运行时生成，不入库）
├── data/                                # WebUI 状态/审计/备份（运行时生成，不入库）
├── game_data/                           # 游戏新闻库（运行时生成，不入库）
├── voice_cache/ image_cache/            # 运行时缓存（自动清理）
└── .env.example                         # 配置模板
```

## 三、消息处理流程

```
QQ 消息 → OneBot V11 协议端 → NoneBot → 核心插件 message_handler（priority 10）
  │
  ├─ 1. 前置过滤：以命令前缀开头的消息跳过（避免与指令插件冲突）
  ├─ 2. 休眠检查：BOT_SLEEP_START ~ BOT_SLEEP_END 期间静默
  ├─ 3. 群聊控制：@/昵称触发 或 GROUP_REPLY_PROBABILITY 随机命中；群冷却检查
  ├─ 4. 内容提取：
  │     ├─ 语音段 → 下载 → 转 wav → Whisper 转文字
  │     ├─ 图片段 → 安全下载 → base64 → LLM Vision 描述
  │     └─ 文本段 → 原文
  ├─ 5. 上下文组装：
  │     ├─ 检索记忆（FTS5 + jieba 分词，top_k 条）
  │     ├─ 读取会话历史（最近 DIALOG_MAX_TURNS 轮）
  │     ├─ 用户画像摘要（姓名/所在地/职业/喜好/关注话题）
  │     └─ 情感上下文（最近消息情感 → 语气提示）
  ├─ 6. 构建 system prompt：人设 JSON + 核心记忆 + 以上上下文
  ├─ 7. 调用 LLM 生成回复
  ├─ 8. 后台任务：LLM 提取新记忆 → 去重 → 入库（asyncio.create_task，不阻塞回复）
  └─ 9. 回复：
        ├─ 文字回复（默认）
        └─ 语音回复（/voicemode 为 always 或语音进语音出时，TTS 合成后发送）
```

关键实现位置：

| 步骤 | 函数 | 文件 |
|------|------|------|
| 消息入口 | `message_handler` | `nonebot_plugin_update_baisuwen/event_handler.py` |
| 戳一戳 | `poke_matcher` | `nonebot_plugin_update_baisuwen/poke.py` |
| 语音处理 | `process_voice_message` | 同上 |
| 图片处理 | `_handle_image_segments` / `handle_image_message` | 核心插件 / `nonebot_plugin_multimodal/image_handler.py` |
| 记忆检索 | `retrieve_memories` | `nonebot_plugin_memory/retrieval.py` |
| system prompt | `_build_system_prompt_with_context` | 核心插件 `event_handler.py` |
| 记忆提取 | `generate_and_store_memory_llm` | 同上 |

## 四、记忆系统

### 4.1 存储模型

每用户两个 SQLite 库（`user_data/short_{uid}.db`、`long_{uid}.db`），表结构相同：

- **memories**：`content`（内容）、`importance`（重要性）、`strength`（强度）、`created_at`、`last_accessed`、`access_count`
- **memories_fts**：FTS5 全文索引（三触发器同步）
- **maintenance_state**：维护计数器（每加 500 条触发一次全量维护）
- **memory_vectors**：语义向量（`ENABLE_VECTOR_SEARCH=true` 时启用，默认关闭）

### 4.2 遗忘算法（幂律衰减）

```
W(t) = strength × (Δhours + 1)^(-β)      # β = MEMORY_BETA，默认 0.5
```

- **访问强化**：检索命中时 `strength += η(1 - strength)`（指数趋近 1）
- **清理**：权重低于 `MEMORY_WEIGHT_THRESHOLD`（0.1）删除；超出容量上限按权重升序清理

### 4.3 记忆生命周期

```
新记忆（importance 默认 0.6）
  → 短期库（最多 2000 条）
  → 升级条件（任一满足）：importance ≥ 0.7 | access_count ≥ 5 | 权重 ≥ 0.5
  → 长期库（最多 5000 条）
```

去重：短库按 jieba 首词哈希分桶 + `difflib` 相似度 ≥ 0.9 合并；长库用 SequenceMatcher ≥ 0.85 判重。冲突记忆（如「喜欢 X」→「现在不喜欢 X」）默认**降权旧记忆**而非删除。

### 4.4 检索

主链路为 **FTS5**（jieba 分词、OR 查询、按 `score × importance` 重排），FTS5 不可用时降级 BM25/LIKE。检索命中后更新记忆的强度与访问次数。向量检索（sentence-transformers 本地模型）作为可选独立 API，暂未接入对话主链路。

### 4.5 维护任务

每天 02:00（可配置）APScheduler 扫描全部用户库，依次执行：清理弱记忆 → 合并相似记忆 → 升级/去重 → 睡眠巩固（重要记忆强度 ×1.05）。单个用户失败不影响其他用户。

## 五、语音链路

```
用户语音 ──> 下载 → silk_to_wav（pilk/ffmpeg）──> Whisper 转文字 ──> 进入对话流程
                                                                    │
Bot 回复 ──────────────────────────────────────────────────────────┤
         └─> TTS 引擎 ─> 长文本按标点断句 + 300ms 静音拼接 ─> 生成 wav ─> 发送语音
```

- **TTS 双引擎**：`TTS_ENGINE=vits`（内置，单音色 <1s）或 `gpt_sovits`（外部项目 GPT-SoVITS，通过 sys.path 注入 + chdir 兼容方式调用）
- **情感角色路由**（GPT-SoVITS）：Level 1 情感匹配（回复情感 → 角色）→ Level 2 关键词匹配（24 角色特征词）→ Level 3 默认角色
- **语音开关**：`/voicemode` 命令设置 auto / always / text 三模式，群聊默认始终文字

## 六、WebUI

- 挂载于 NoneBot 同一 FastAPI 应用（`/webui` 前缀，端口同 `PORT`）
- **认证**：QQ 内 `/auth <token>` 双通道登录（token 5 分钟有效），session 为 HMAC 签名 cookie（24h）
- **权限**：super（SUPERUSERS）/ admin / user 三级
- **页面**：仪表盘、插件管理、.env 编辑器、人设编辑器（热重载）、记忆浏览、审计日志、备份恢复
- **插件管理**：扫描 `src/plugins/` 读 `__plugin_meta__`，开关状态持久化 `data/webui_plugin_states.json`
- **审计**：所有管理操作追加写入 `data/webui_audit.jsonl`
- **重启**：写重启信号 → `os._exit(42)` → 看门狗脚本（`start_bot.bat`）检测 exit code 42 自动重启

## 七、定时任务汇总

| 任务 | 时间 | 说明 |
|------|------|------|
| 记忆维护 | 每天 02:00 | 清理/合并/升级/巩固 |
| 图片缓存清理 | 每天 00:30 | 删除 7 天前的 `image_cache/` 文件 |
| 游戏新闻刷新 | 每天 08:00 | 运行 `tools/game-event-progress/scripts/update.py` |
| 游戏新闻推送 | 每天 08:30 | 渲染活动速报图推送订阅者 |
| 紧迫活动检查 | 每 10/20 点 | 48h 内结束的活动即时提醒 |

## 八、外部依赖与数据流

```
┌────────────┐   HTTP(HTTPS)   ┌─────────────┐
│ DeepSeek   │◄───────────────►│ 核心插件     │
│ API        │   对话/图片/提取 │             │
└────────────┘                 └──────┬──────┘
                                      │
   ┌──────────────┐    subprocess    ┌▼───────────┐    SQLite    ┌────────────────┐
   │ game-event-  │◄────────────────►│ gamenews   │◄────────────►│ game_data/     │
   │ progress     │    update.py     │ 插件        │   订阅/事件   │ game_news.db   │
   └──────────────┘                  └────────────┘               └────────────────┘
                                      │
   ┌──────────────┐   sys.path+chdir ┌▼───────────┐
   │ GPT-SoVITS   │◄────────────────►│ TTS 引擎   │
   │ 外部项目      │   推理调用        │ (gpt_sovits)│
   └──────────────┘                  └────────────┘
```

## 九、设计要点

1. **Library 型插件**：ASR / TTS / 多模态 / 情感 / 画像均为无命令的 library 插件，由核心插件编排调用，职责单一、可独立替换。
2. **会话作用域**：群聊按群共享一个会话（`group_{群号}`），私聊按人独立（`private_{QQ号}`）；会话 30 分钟无消息自动清理。
3. **后台记忆提取**：LLM 记忆提取在回复后异步执行，不增加用户等待时间；提取失败不影响对话。
4. **命令避让**：核心消息处理器跳过命令前缀，避免与指令插件竞争。
5. **安全设计**：外部 URL 下载统一做 SSRF 防护与哈希命名；WebUI 全部管理操作留审计。
6. **数据不入库**：所有用户数据与运行时产物均被 .gitignore 排除，仓库保持干净。
