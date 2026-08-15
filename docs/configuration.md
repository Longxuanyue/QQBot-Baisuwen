# 配置指南

本项目使用 `.env` 文件进行配置，位于项目根目录。首次使用请执行：

```bash
# Linux/macOS
cp .env.example .env

# Windows
copy .env.example .env
```

然后编辑 `.env`，填入你的实际配置。所有配置项均有默认值，**唯一必填项是 `DEEPSEEK_API_KEY`**。

> 修改 `.env` 后需重启 Bot 才会生效。修改 `.env` 不会影响已存储在数据库中的记忆数据。

## 配置项总览

| 配置项 | 默认值 | 必填 | 说明 |
|--------|--------|------|------|
| `DEEPSEEK_API_KEY` | - | ✅ | DeepSeek API 密钥 |
| `SUPERUSERS` | - | ✅ | 超级用户 QQ 号（JSON 数组） |
| `BOT_NICKNAME` / `NICKNAME` | - | 建议 | 机器人昵称，用于群聊呼唤检测 |
| `PERSONALITY_FILE` | 内置人设文件 | 否 | 人设配置文件路径 |

其余配置按功能分组，见下文。所有配置项都可省略（使用默认值）。

## 一、运行环境

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `ENVIRONMENT` | `dev` | `dev` = 开发环境（DEBUG 日志）；`prod` = 生产环境（ERROR 级别日志） |
| `DRIVER` | `~fastapi+~websockets` | NoneBot 驱动器组合，同时提供 REST API 与反向 WebSocket，一般固定不变 |
| `HOST` | `127.0.0.1` | 服务监听地址。`127.0.0.1` 仅本机访问；`0.0.0.0` 允许局域网/公网访问（有安全风险） |
| `PORT` | `42200` | 服务监听端口，需与 OneBot 协议端的反向 WS 地址端口一致 |
| `LOG_LEVEL` | `INFO` | 日志级别：`DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `UVICORN_LOG_LEVEL` | `info` | Uvicorn ASGI 服务器日志级别 |

## 二、QQ 机器人身份

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `SUPERUSERS` | 无 | 超级用户 QQ 号列表（JSON 数组，如 `["123456789"]`）。超管拥有管理命令、WebUI 登录、强制操作等最高权限 |
| `BOT_NICKNAME` | 无 | 机器人昵称，用户消息包含该昵称时触发回复 |
| `NICKNAME` | 无 | NoneBot 内置 to_me 检测昵称列表（JSON 数组），支持多昵称 |
| `PERSONALITY_FILE` | `src/plugins/nonebot_plugin_update_baisuwen/personality_traits.json` | 人设文件路径（相对于项目根目录）。参见 [personality.md](personality.md) |

## 三、DeepSeek LLM

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DEEPSEEK_API_KEY` | 无（必填） | DeepSeek API 密钥，从 [platform.deepseek.com](https://platform.deepseek.com/api_keys) 获取 |
| `DEEPSEEK_API_BASE` | `https://api.deepseek.com` | API 基础 URL，可替换为任何 OpenAI 兼容端点 |
| `DEEPSEEK_MODEL` | `deepseek-v4-pro` | 模型名称。DeepSeek 推荐 `deepseek-chat`（V3）/ `deepseek-v4-pro`。**多模态图片理解需要模型支持 vision 能力** |
| `HTTPX_TIMEOUT` | `60` | LLM HTTP 请求超时（秒），生成长回复建议 ≥ 60 |
| `LLM_MAX_CONTEXT_TOKENS` | `8192` | 单次请求上下文预算（token 估算值）。超出时按优先级裁剪：最旧对话历史 → 记忆/画像 → system prompt 尾部 |
| `LLM_MAX_RETRIES` | `2` | LLM 调用失败重试次数（429/5xx/网络错误时指数退避） |
| `LLM_RETRY_BACKOFF` | `1.0` | 重试退避基础间隔（秒），实际等待 = backoff × 2^(attempt-1)，上限 10s |
| `LLM_STREAM_REPLY` | `false` | 流式回复（实验性）：边生成边发送，新消息替换上一条。开启后群聊消息会频繁发送/删除，慎用 |
| `MEMORY_EXTRACT_MIN_INTERVAL` | `300` | 记忆提取最小间隔（秒）。群聊非@消息与过短消息不触发提取 |
| `MEMORY_EXTRACT_MODEL` | 空 | 记忆提取专用模型（可填更便宜的型号），留空与主对话同模型 |

## 四、OneBot V11 协议

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `ONEBOT_WS_REVERSE_URL` | `ws://127.0.0.1:42200/onebot/v11/ws` | 反向 WebSocket 地址，需在 QQ 协议端（NapCat/Lagrange/LLOneBot）中配置相同地址 |

## 五、群聊行为

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `GROUP_REPLY_PROBABILITY` | `0` | 非 @/非昵称触发时的随机回复概率（0~1）。`0` = 仅响应明确指令与呼唤（推荐，避免骚扰）；`0.05` = 5% 概率主动搭话 |
| `GROUP_REPLY_COOLDOWN` | `5.0` | 同一群内两次回复的最小间隔（秒） |

## 六、对话管理

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DIALOG_MAX_TURNS` | `20` | 会话保留的最大对话轮数，超出后最早的轮次移出上下文窗口 |
| `DIALOG_SESSION_TTL` | `1800` | 会话超时时间（秒），超时无新消息自动清理。`1800` = 30 分钟 |
| `DIALOG_SUMMARY_THRESHOLD` | `16` | 会话轮数超过该值后，后台把最早的一半消息压缩成滚动摘要注入上下文 |
| `DIALOG_SUMMARY_MIN_INTERVAL` | `600` | 两次滚动摘要之间的最小间隔（秒） |
| `REPLY_CACHE_TTL` | `600` | 相同消息回复缓存有效期（秒）；时间敏感消息不命中；设为 `0` 关闭 |

## 七、休眠与定时任务

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `BOT_SLEEP_START` | `23:30` | 休眠开始时间（HH:MM），休眠期间不响应任何消息（不消耗 Token） |
| `BOT_SLEEP_END` | `06:00` | 休眠结束时间（HH:MM），支持跨天 |
| `MEMORY_MAINTENANCE_HOUR` | `2` | 记忆维护任务执行小时（24 小时制），执行遗忘衰减、短期→长期升级、去重合并等 |
| `MEMORY_MAINTENANCE_MINUTE` | `0` | 记忆维护任务执行分钟 |

## 八、记忆系统


### 检索优化（v3）

记忆检索已升级为多级链路，无需配置即可生效：

1. **FTS5 双表**：`unicode61`（英文/数字）+ `trigram`（中文任意子串）。`「咖啡」` 现在可以命中 `「用户喜欢喝咖啡」`
2. **空结果降级链**：FTS 无结果时自动降级 `LIKE`（核心词+别名）→ `BM25`
3. **领域词典**：`src/plugins/nonebot_plugin_memory/data/jieba_dict.txt`（游戏名/梗/网络词，修复 `明日方舟` 被切碎的问题）
4. **动态词典**：群聊学习每日任务从消息共现中学习新词，持久化到 `user_data/dynamic_jieba_dict.txt`
5. **别名扩展**：内置 `data/aliases.json`（`粥`→`明日方舟`）+ 群风格卡提炼的群级别名，检索时自动 OR 扩展
6. **上下文感知**：检索自动拼接最近 2 轮对话，解决 `「那个活动」` 类指代
7. **向量语义检索**（可选）：`ENABLE_VECTOR_SEARCH=true` 后夜间为记忆计算向量，检索时 RRF 融合字面+语义结果

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `ENABLE_VECTOR_SEARCH` | `false` | 启用向量语义检索（需 `pip install sentence-transformers`，首次运行下载模型约 100MB） |
### 基本配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `MEMORY_TOP_K` | `5` | 每次检索返回的最相关记忆条数 |
| `MEMORY_CONTEXT_HISTORY_LEN` | `2` | 上下文感知检索时保留的最近对话轮数 |
| `MEMORY_DEFAULT_IMPORTANCE` | `0.6` | 新记忆的默认重要性评分（0~1） |

### 存储路径

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `MEMORY_SHORT_TERM_DB` | 空 | 短期记忆数据库路径（单用户模式），留空用项目根目录 `short_term.db` |
| `MEMORY_LONG_TERM_DB` | 空 | 长期记忆数据库路径（单用户模式），留空用项目根目录 `long_term.db` |
| `MEMORY_USER_DATA_DIR` | `user_data` | 多用户模式分库目录：`user_data/short_{uid}.db`、`user_data/long_{uid}.db` |

### 容量限制

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `MEMORY_SHORT_TERM_MAX` | `2000` | 短期记忆库最大条数，超出后清理最旧/最低权重记忆 |
| `MEMORY_LONG_TERM_MAX` | `5000` | 长期记忆库最大条数 |

### 遗忘算法（幂律衰减）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `MEMORY_BETA` | `0.5` | 幂律衰减指数，控制遗忘速度：`0.3` 慢 / `0.5` 中等 / `0.8` 快 |
| `MEMORY_ETA` | `0.3` | 复习增强学习率，访问后的记忆强化程度：`0.1` 轻微 / `0.3` 中等 / `0.5` 大幅 |
| `MEMORY_WEIGHT_THRESHOLD` | `0.1` | 记忆权重低于该阈值时自动清理 |

### 记忆升级（短期 → 长期）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `MEMORY_UPGRADE_IMPORTANCE_THRESHOLD` | `0.7` | 升级所需的重要性阈值 |
| `MEMORY_UPGRADE_ACCESS_COUNT_THRESHOLD` | `5` | 升级所需的最小访问次数 |
| `MEMORY_UPGRADE_WEIGHT_THRESHOLD` | `0.5` | 升级所需的权重阈值 |

### 去重与合并

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `MEMORY_SIMILARITY_THRESHOLD` | `0.85` | 相似度高于此值判定为新记忆与已有记忆重复 |
| `MEMORY_MERGE_SIMILARITY_THRESHOLD` | `0.9` | 相似度高于此值时将两条记忆合并为一条 |

## 九、ASR 语音识别（Whisper）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `ENABLE_ASR` | `true` | 是否启用语音识别 |
| `ASR_MODEL_SIZE` | `small` | Whisper 模型大小：`tiny` ~39M / `base` ~74M / `small` ~244M（推荐）/ `medium` ~769M / `large` ~1.5G |
| `ASR_DEVICE` | `cuda` | `cuda` = GPU 推理（快 5~20 倍）；`cpu` = CPU 推理 |
| `ASR_LANGUAGE` | `zh` | 识别语言：`zh` / `en` / `ja`，留空或 `auto` = 自动检测 |

> 首次启用 ASR 会自动下载 Whisper 模型，需联网。

## 十、TTS 语音合成

### 引擎选择

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `ENABLE_TTS` | `true` | 是否启用语音合成 |
| `TTS_ENGINE` | `vits` | `vits` = 原生 VITS 模型（单音色，<1s 生成，零外部依赖）；`gpt_sovits` = GPT-SoVITS 模型（支持多角色情感路由，需预先配置模型与参考音频） |

### VITS 引擎参数

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `TTS_MODEL_PATH` | `models/G_latest.pth` | VITS 模型文件路径（绝对路径或相对项目根目录） |
| `TTS_CONFIG_PATH` | `models/finetune_speaker.json` | VITS 配置文件路径（JSON，定义说话人） |
| `TTS_ALWAYS` | `false` | `true` = 所有回复都用语音；`false` = 仅当用户发语音时回复语音 |
| `TTS_SPEED` | `1.0` | 语速（>1 加快，<1 减慢） |
| `TTS_NOISE_SCALE` | `0.667` | 语调随机性/情感幅度（0.3~0.8），越高语调越丰富 |
| `TTS_NOISE_SCALE_W` | `0.8` | 时长随机性/节奏变化（0.3~1.0） |
| `TTS_MAX_SENTENCE_LEN` | `50` | 长文本拆分单句最大字符数 |
| `TTS_SILENCE_MS` | `300` | 句间静音时长（毫秒） |
| `TTS_DEVICE` | `cuda:0` | 运算设备：`cuda:0` / `cpu`，留空自动检测 |

### GPT-SoVITS 引擎参数（仅 `TTS_ENGINE=gpt_sovits` 时生效）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `GPT_SOVITS_CONFIG` | 无 | GPT-SoVITS 推理配置路径（指向其项目下 `tts_infer.yaml`，绝对路径） |
| `GPT_SOVITS_VERSION` | `v2` | 模型版本：`v1` / `v2` / `v3` / `v4` / `v2Pro` / `v2ProPlus`，需与训练权重版本匹配 |
| `GPT_SOVITS_DEFAULT_CHARACTER` | 无 | 情感路由兜底角色，需与 `ref_audio/index.json` 或 `characters.json` 中角色名一致 |
| `GPT_SOVITS_DEVICE` | `cuda:0` | 推理设备 |
| `GPT_SOVITS_IS_HALF` | `true` | 是否 fp16 半精度（显存减半，速度略快） |
| `GPT_SOVITS_GPT_WEIGHTS` | 空 | 自定义 GPT 权重路径（相对 GPT-SoVITS 根目录），留空用 `tts_infer.yaml` 默认底模 |
| `GPT_SOVITS_SOVITS_WEIGHTS` | 空 | 自定义 SoVITS 权重路径 |

## 十一、多模态（图片理解）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `ENABLE_MULTIMODAL` | `true` | `true` = 用户发图片时通过 LLM Vision API 理解内容；`false` = 仅记录不分析 |

> ⚠️ 需 `DEEPSEEK_MODEL` 支持 vision 能力。

## 十二、游戏新闻（GAMENEWS）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `GAMENEWS_ENABLED` | `true` | 是否启用游戏新闻插件 |
| `GAMENEWS_CRON_HOUR` / `GAMENEWS_CRON_MINUTE` | `8` / `0` | 数据自动刷新时间 |
| `GAMENEWS_PUSH_HOUR` / `GAMENEWS_PUSH_MINUTE` | `8` / `30` | 每日综合推送时间 |
| `GAMENEWS_URGENCY_HOURS` | `48` | 紧迫事件阈值（小时内即将结束的视为紧迫） |
| `GAMENEWS_TARGET_GROUPS` | `[]` | 每日推送目标群号（JSON 数组，如 `["798807723"]`） |

## 十三、明日方舟森空岛（Skland，外部插件）

以下为 [nonebot-plugin-skland](https://github.com/FrostN0v0/nonebot-plugin-skland) 的配置项，前缀 `skland__` 是插件配置自动映射的格式：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `skland__github_proxy_url` | 空 | GitHub 代理 URL，加速资源下载 |
| `skland__github_token` | 空 | GitHub Token（提高 API 限额） |
| `skland__check_res_update` | `true` | 启动时检查资源文件更新 |
| `skland__background_source` | `default` | 背景图片来源：`default` / `custom` |
| `skland__endfield_background_simple` | `false` | 终末地背景图简化模式 |
| `skland__rogue_background_source` | `rogue` | 集成战略战绩背景来源：`rogue` / `custom` |
| `skland__argot_expire` | `300` | 暗语消息过期时间（秒） |
| `skland__gacha_render_max` | `30` | 明日方舟抽卡渲染图最多卡池数 |
| `skland__ef_gacha_render_max` | `5` | 终末地抽卡渲染图最多卡池数 |

## 十四、HTML 渲染（Playwright）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `HTMLRENDER_BROWSER` | `chromium` | 浏览器类型：`chromium` / `firefox` / `webkit` |
| `HTMLRENDER_BROWSER_EXECUTABLE_PATH` | 空 | 浏览器可执行文件绝对路径。Windows 可用 Edge 替代 Chromium 以减少下载量 |


## 十五、群聊学习（nonebot_plugin_groupmind）

群聊学习为 bot 提供群级记忆、群画像统计与群风格卡。**默认全局关闭**，
需要先在 `.env` 开启 `GROUP_LEARNING=true`，再由群主/管理员用 `/群学习 on` 逐群启用。

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `GROUP_LEARNING` | `false` | 总开关。关闭时全部群不采集、不学习 |
| `GROUP_LEARN_DEFAULT` | `false` | 新群默认是否开启学习（建议保持关闭，由群主显式开启） |
| `GROUP_MEMORY_EXTRACT_TIMES` | `12:30,20:30` | 群记忆批量提取时刻（每日多次，逗号分隔） |
| `GROUP_STYLE_CARD_TIME` | `21:00` | 群风格卡每日生成时刻 |
| `GROUP_STYLE_CARD_INTERVAL` | `500` | 或每累计 500 条群消息触发一次风格卡（取先到） |
| `GROUP_STYLE_MODEL` | 空 | 群总结专用模型（可选，留空用主对话模型） |
| `GROUP_CONTEXT_MAX_TOKENS` | `200` | 注入 system prompt 的群上下文块预算（token 估算值） |
| `GROUP_MEMORY_TOP_K` | `3` | 注入的群记忆条数 |
| `GROUP_ADAPTIVE_PROBABILITY` | `false` | 是否允许"氛围分"调节群回复概率（需 `GROUP_REPLY_PROBABILITY` > 0 才生效） |
| `GROUP_HISTORY_KEEP` | `500` | 群消息流水保留条数（超出清理最旧） |

### 群学习命令（`/群学习`）

| 命令 | 权限 | 说明 |
|------|------|------|
| `/群学习 on` / `off` | 群主/管理员 | 开启/关闭本群学习 |
| `/群学习 status` | 所有人 | 本群学习状态（记忆数、话题、活跃时段、风格卡） |
| `/群学习 clear` | 群主/管理员 | 清空本群学习数据 |
| `/群学习 summary` | 超级用户 | 手动触发一次群记忆提取与风格卡生成 |

群数据存放于 `user_data/group_{群号}.db`（群记忆、消息流水、统计、风格卡），
可通过 WebUI「记忆浏览」页的群列表查看与删除群记忆。
## 完整示例

`.env.example` 中的每一项都带有默认值与说明注释，修改时请以 `.env.example` 为基准，避免遗漏或拼写错误。

## 常见问题

**Q：改完配置不生效？**
A：重启 Bot。部分配置（如 `ENABLE_ASR`）仅在启动时读取。

**Q：`DEEPSEEK_MODEL` 用什么模型？**
A：纯对话用 `deepseek-chat` 或 `deepseek-v4-pro`；需要图片理解时，必须选择支持 vision 的模型并开启 `ENABLE_MULTIMODAL=true`。

**Q：如何清空记忆库？**
A：停止 Bot，删除项目根目录下 `short_term.db`、`long_term.db`（或 `user_data/` 目录），重启即可。删除前建议先备份。
