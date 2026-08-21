# Changelog

本项目的所有重要变更都会记录在此文件中。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [1.4.0] - 2026-08-21

### Added

- 按群响应控制：`/群响应 on|off|reset|status` 命令（群主/管理员/超管可在群内逐群开关，超管可设置全局默认、查看/远程控制所有群）；关闭的群完全不响应消息（含 @ 与昵称呼唤），戳一戳也不回应；新群默认响应状态由 `GROUP_RESPONSE_DEFAULT` 控制
- 群聊语音回复模式：`/群语音 auto|voice|text|reset` 命令（群主/管理员/超管可在群内逐群设置，超管可设置全局默认、列出所有显式设置群、远程设置指定群）；群聊语音模式与私聊 `/voicemode` 互相隔离，默认模式由 `GROUP_VOICE_DEFAULT` 控制
- 群迎新插件 `nonebot_plugin_welcome`：新成员入群自动发送欢迎消息（默认“欢迎欢迎~”），超级用户可用 `/迎新 <内容>` 自定义内容、`/迎新` 查看、`/迎新 重置` 恢复默认

### Changed

- `nonebot_plugin_help` 升级至 0.4.0：新增从 matcher 动态提取 `on_command` 指令（含别名），未提供元数据的插件也能在 `/help` 中列出真实指令名

## [1.3.0] - 2026-08-15

### Added

- Token 预算管理（`LLM_MAX_CONTEXT_TOKENS`）：请求超出预算时自动裁剪最旧对话历史与附加信息，避免超窗
- 对话滚动摘要：会话超过 `DIALOG_SUMMARY_THRESHOLD` 轮后，后台将最早消息压缩为纪要注入上下文
- 相同消息回复缓存（`REPLY_CACHE_TTL`）：TTL 内重复提问直接复用回复，节省 API 调用
- LLM 调用失败自动重试 + 指数退避（`LLM_MAX_RETRIES` / `LLM_RETRY_BACKOFF`），高峰不再一次失败即兜底
- 流式回复（`LLM_STREAM_REPLY`，默认关闭，实验性）：边生成边发送，新消息替换上一条
- 记忆提取节流（`MEMORY_EXTRACT_MIN_INTERVAL`）与专用模型（`MEMORY_EXTRACT_MODEL`）；群聊非@消息不再触发提取
- 新增 `tools/cleanup_empty_dbs.py`：一键清理历史遗留的 0 条记忆空库

### Changed

- **速度**：ASR 识别、silk→wav 转换、TTS 合成分散到线程池，不再阻塞事件循环；多图片并发下载；检索命中改为单连接批量更新（替代逐条开连接）；FTS5 可用性结果缓存
- **Token**：对话历史只注入一次（移除 system prompt 中重复的历史全文）；记忆/画像注入体积裁剪；画像缓存 TTL 后台重建（`PROFILE_REFRESH_SECONDS`）
- **记忆管理**：数据库惰性建库——用户仅发言但 bot 未回复时不再创建空库文件；夜间维护跳过空库并并发执行（上限 8 线程）
- 语音模式读取带内存缓存，且不再为无库用户创建数据库文件
- 新增群聊学习（`GROUP_LEARNING`，默认关闭）：群级记忆批量提取、群画像统计（活跃时段/话题/昵称/@关系/氛围分）、群风格卡、自适应回复概率、`/群学习` 管理命令
- 群聊历史注入带说话人标注（昵称优先），避免回复张冠李戴
- WebUI 记忆浏览新增群列表，可查看/删除群记忆
- **记忆检索 v3**：FTS5 trigram 双表（中文子串命中）、空结果 LIKE/BM25 降级链、领域词典（`data/jieba_dict.txt`）、群聊共现动态词典、别名扩展（内置+群级别名）、检索自动拼接最近对话（指代消解）、可选向量语义检索（`ENABLE_VECTOR_SEARCH`，RRF 融合）
- 全项目分词统一走 `text_utils`（归一化 + 词典 + lru_cache 缓存 + 后台预热）
- 旧库自动升级：首次 `init_database` 时重建 trigram 索引（`rebuild`）并将触发器升级为双表同步（存量用户库/群库升级后即可 trigram 命中旧记忆）

## [1.2.1] - 2026-08-04

### Changed

- 优化 Windows 端一键部署脚本 — 显式安装 nonebot2 框架本体、API Key 允许留空、修复批处理脚本行尾导致的解析不稳定问题
- 新增人设模板文件 `personality_traits.template.json`，便于自定义角色人设
- `.env.example` 中 GPT-SoVITS 配置示例改为占位符，避免误用示例路径

### Fixed

- 修复部分配置文件

## [1.2.0] - 2026-08-01

### Fixed

- 修复部分漏洞问题

## [1.1.0] - 2026-07-29

### Added

- 新增 GPT-SoVITS 模型支持 — TTS 模块现已兼容 GPT-SoVITS 与 VITS 双模型，用户可按需选择
- 新增游戏动态推送功能 — 集成 game-event-progress，支持多款游戏的活动 / 卡池信息推送

### Fixed

- 修复部分无法正确读取 `.env` 配置的问题 — 优化配置解析逻辑，确保环境变量稳定加载

## [1.0.0] - 2026-07-24

### Added

- 初始代码库版本，基于 NoneBot2 + DeepSeek 的 QQ 智能陪伴机器人，包含：
  - 智能对话与独立角色人格（狼族少女「小玖」）
  - 双层级记忆系统（短期 + 长期记忆，幂律遗忘曲线）
  - 语音交互（Whisper ASR + VITS TTS）
  - 多模态图像理解、用户画像、情感分析
  - 群聊支持、WebUI 管理面板、定时休眠
  - 明日方舟-卫戍协议工具箱

[Unreleased]: https://github.com/Longxuanyue/QQBot-Baisuwen/compare/v1.3.0...HEAD
[1.3.0]: https://github.com/Longxuanyue/QQBot-Baisuwen/compare/v1.2.1...v1.3.0
[1.2.1]: https://github.com/Longxuanyue/QQBot-Baisuwen/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/Longxuanyue/QQBot-Baisuwen/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/Longxuanyue/QQBot-Baisuwen/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Longxuanyue/QQBot-Baisuwen/releases/tag/v1.0.0
