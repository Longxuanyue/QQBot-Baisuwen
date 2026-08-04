# Changelog

本项目的所有重要变更都会记录在此文件中。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

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

[Unreleased]: https://github.com/Longxuanyue/QQBot-Baisuwen/compare/v1.2.1...HEAD
[1.2.1]: https://github.com/Longxuanyue/QQBot-Baisuwen/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/Longxuanyue/QQBot-Baisuwen/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/Longxuanyue/QQBot-Baisuwen/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Longxuanyue/QQBot-Baisuwen/releases/tag/v1.0.0
