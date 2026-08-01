# 开发指南

本文档面向想为本项目贡献代码或二次开发的开发者。阅读前建议先看 [architecture.md](architecture.md) 了解整体结构。

## 一、开发环境

```bash
# 安装开发依赖（ruff / pyright）
pip install -e .[dev]

# 代码检查
ruff check src tools
ruff format --check src tools

# 类型检查
pyright src
```

代码规范见 `pyproject.toml` 的 `[tool.ruff]`：行宽 88、大量规则集（F/W/E/I/ANN/B/SIM/PERF 等）。提交前请确保 `ruff check` 通过。

## 二、插件结构约定

所有本地插件位于 `src/plugins/`，每个插件一个目录（`nonebot_plugin_xxx/`）：

```
nonebot_plugin_xxx/
├── __init__.py    # 插件入口：matcher 注册 + PluginMetadata
├── config.py      # 配置（pydantic-settings 或常量）
└── ...            # 业务模块
```

`pyproject.toml` 中 `[tool.nonebot.plugins]` 使用 `"@local"` 自动发现 `src/plugins/` 下所有插件，**新增目录即自动加载**，无需额外配置。

插件分为两类：

| 类型 | 特点 | 示例 |
|------|------|------|
| **application** | 注册命令/事件响应器 | gamenews、strongholdtools、admin、webui |
| **library** | 无命令，提供引擎/服务供核心插件调用 | tts、asr、multimodal、sentiment、profile |

## 三、命令注册规范

项目对 NoneBot 优先级有约定俗成的划分：

| 优先级 | 用途 | 示例 |
|--------|------|------|
| 1 | 系统级命令（block=True） | `/admin`、`/help`、`/auth` |
| 5 | 功能命令（block=True） | `/voicemode`、`/卫戍协议`、游戏新闻系列 |
| 10 | 聊天主链路（block=False） | `message_handler` |

聊天处理器会跳过以命令前缀开头的消息（`event_handler.py` 防御性检查），因此新命令**必须 block=True** 且优先级 < 10，否则会同时被聊天链路消费。

## 四、完整命令清单

### 管理命令（`/admin`，仅 SUPERUSER）

| 命令 | 说明 |
|------|------|
| `/admin` | 帮助列表 |
| `/admin status` | 进程状态、记忆库统计 |
| `/admin memory <QQ号>` | 查看指定用户的记忆统计 |
| `/admin reload personality` | 热重载人设（无需重启） |
| `/admin reload config` | 重载 `.env` 环境变量 |
| `/admin sleep on` / `off` | 强制休眠 / 恢复作息 |

### 用户命令

| 命令 | 说明 | 插件 |
|------|------|------|
| `/help`、`/帮助` | 帮助索引；`/help <插件名>` 查看详情 | help |
| `/voicemode <auto\|always\|text>` | 私聊语音回复模式 | update_baisuwen |
| `/auth <token>` | WebUI 登录（SUPERUSER） | webui |
| `/游戏新闻`、`/新闻` | 查看游戏新闻 | gamenews |
| `/卡池`、`/banner` | 查看卡池信息 | gamenews |
| `/活动`、`/event` | 查看活动列表 | gamenews |
| `/紧急活动`、`/紧迫`、`/即将截止` | 查看即将截止活动 | gamenews |
| `/订阅新闻` / `/取消新闻` | 订阅/退订每日推送 | gamenews |
| `/游戏新闻状态`、`/新闻状态` | 推送状态 | gamenews |
| `/强制更新新闻` | 立即刷新数据（SUPERUSER） | gamenews |
| `/卫戍协议 [敌人名/编号]` | 明日方舟卫戍协议敌人查询 | strongholdtools |
| 戳一戳 | 响应「嗷呜？你要干嘛？」 | update_baisuwen |

另有外部商店插件：`nonebot-plugin-skland`（森空岛查询）、`nonebot-plugin-status`（运行状态）、`nonebot-plugin-docs`。

### 帮助信息接入

`/help` 插件自动收集命令，三种来源按序合并：

1. `collector.py` 中 `_KNOWN_COMMANDS` 手动映射（优先级最高）
2. `PluginMetadata.extra["commands"]`（推荐新插件使用）
3. Alconna command_manager 枚举

推荐在插件的 `PluginMetadata.extra` 中声明命令，这样无需改动 help 插件即可被收集：

```python
from nonebot import get_plugin_config
from nonebot.plugin import PluginMetadata

__plugin_meta__ = PluginMetadata(
    name="示例插件",
    description="一个示例",
    usage="/示例命令 <参数>",
    type="application",
    homepage="https://github.com/xxx/xxx",
    supported_adapters={"~onebot.v11"},
    extra={"commands": [("/示例命令 <参数>", "示例命令说明")]},
)
```

WebUI 插件页与 help 插件都会读取 `__plugin_meta__`。

## 五、扩展点

### 5.1 服务抽象层

核心插件 `nonebot_plugin_update_baisuwen/abc.py` 定义了服务契约：

| 抽象类 | 对应服务 | 当前实现 |
|--------|----------|----------|
| `BaseLLMClient` | LLM 客户端 | `llm_client.py::DeepseekClient` |
| `BaseASREngine` | 语音识别 | `nonebot_plugin_asr::WhisperASR` |
| `BaseTTSEngine` | 语音合成 | VITS `TTSInference` / `GPTSoVITSEngine` |
| `BaseMemoryBackend` | 记忆后端 | `nonebot_plugin_memory::UserMemoryManager` |
| `BaseDialogManager` | 会话管理 | `nonebot_plugin_dialog::DialogManager` |
| `BaseSentimentAnalyzer` | 情感分析 | `nonebot_plugin_sentiment::SentimentAnalyzer` |
| `BaseProfileBuilder` | 用户画像 | `nonebot_plugin_profile::ProfileBuilder` |

新服务实现对应 ABC 后，在 `event_handler.py::init_services` 中接线即可。核心插件对所有可选模块的调用均包裹 try/except——**服务缺失或抛异常时静默降级**，不会拖垮对话。

### 5.2 配置模式

- **主插件**：pydantic-settings 分组模型（`LLMConfig` / `ASRConfig` / `TTSConfig` / `MemoryConfig` / `ScheduleConfig` / `GroupChatConfig`），`model_validator` 从 `os.environ` 兜底读取（嵌套 BaseModel 的 env 查找历史坑）
- **独立插件**（tts/gamenews 等）：模块导入时手动 `load_dotenv()` 再读常量
- 新插件建议统一走 pydantic-settings，并把新键同步补进 `.env.example`（WebUI 配置页直接读取 `.env` 文件）

### 5.3 与聊天链路的集成

消息处理 `event_handler.py::handle_message` 的执行序：

```
休眠检查 → 命令前缀跳过 → 语音转文字 → 图片理解 → 空文本短路
→ 群聊概率/冷却 → 写入会话 → 检索记忆 → 拼 system prompt → LLM
→ 后台记忆提取 → 回复（文字/语音）
```

要挂接新的「内容感知」能力（如视频理解、链接解析），在 `handle_message` 提取段追加即可；要注入新的上下文，在 `_build_system_prompt_with_context` 追加（每项独立 try/except）。

### 5.4 记忆 API

```python
from nonebot_plugin_update_baisuwen.memory_manager import get_manager

mgr = get_manager(user_id)
mgr.store_memory(content, importance)      # 写入短期库
mgr.retrieve_memories(query, top_k=5)      # 检索（FTS5，自动更新强度）
mgr.cleanup()                              # 清理弱记忆
mgr.merge_similar()                        # 合并相似记忆
mgr.upgrade_and_deduplicate()              # 升级+去重
```

CLI 工具（`tools/memory_cli.py`）可离线管理：`list` / `search` / `backup` / `stats` / `clean`。

### 5.5 定时任务

使用 `nonebot-plugin-apscheduler`（项目已在 pyproject 依赖中）。示例见 `nonebot_plugin_memory/scheduler.py`（夜间维护）与 `nonebot_plugin_gamenews/__init__.py`（三组任务）。

## 六、已知限制（重要）

以下问题来自代码审计，开发时请注意：

1. **`DIALOG_MAX_TURNS` / `DIALOG_SESSION_TTL` 是死配置** — `dialog/manager.py` 读取的是 `dialog/config.py` 的硬编码常量（20 / 1800），`.env` 中的同名键不生效。
2. **`BOT_NICKNAME` 未被消费** — @/昵称检测依赖 NoneBot 的 `NICKNAME` 环境变量（`event.to_me`），`BOT_NICKNAME` 字段定义了但从未读取。
3. **`ENABLE_VECTOR_SEARCH` 未接入主链路** — 向量检索（`embedding.py`）是独立 API，`retrieve_memories` 主入口仍走 FTS5/BM25。
4. **ServiceRegistry 未接线** — `registry.py` 的拓扑初始化已实现但无模块调用，`/admin status` 的服务图标恒为空。
5. **情感分析 `both` 模式缺陷** — `analyze()` 在规则置信度不足时直接返回 neutral，从不调用 `analyze_llm`，LLM 情感路径实际不可达。
6. **画像缓存永不刷新** — `profiler.get_profile_summary` 只在首次构建，`PROFILE_UPDATE_INTERVAL` 是死代码。
7. **GPT-SoVITS 路径硬编码** — `gpt_sovits_engine.py` 固定 `D:/GPT-SoVITS-main`，换机器需改代码（`GPT_SOVITS_CONFIG` 只覆盖配置文件）。
8. **`OWNER_QQ` 硬编码** — `personality.py` 中主人判定使用常量 `"2461292801"`，而非 `SUPERUSERS`。
9. **`/admin sleep off` 恢复值硬编码** 23:30，与代码默认值 22:00、`.env.example` 的 23:30 三处不一致。

修复上述问题时，请保持现有行为兼容（配置项以 `.env` 为准、缺失时降级），并更新 [configuration.md](configuration.md) 中的对应条目。

## 七、发布流程

1. 修改代码，`ruff check` + `pyright` 通过
2. 若引入新配置：更新 `.env.example` 与 `docs/configuration.md`
3. 若新增命令：更新 `docs/development.md` 命令清单
4. 更新 `CHANGELOG.md`（Keep a Changelog 格式）
5. 打 tag 并创建 GitHub Release（模型文件随 Release 分发）
