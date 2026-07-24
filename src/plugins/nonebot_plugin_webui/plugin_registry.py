"""
插件注册中心：发现、元数据管理、开关控制
"""

import importlib
import importlib.util
import json
import os
import pkgutil
from typing import Optional

from nonebot import logger

from .config import PLUGIN_STATES_FILE


class PluginMeta:
    """插件元数据"""

    def __init__(
        self,
        name: str,
        description: str = "",
        version: str = "0.1.0",
        author: str = "",
        category: str = "feature",
        enabled: bool = True,
        path: str = "",
        source: str = "custom",
    ):
        self.name = name
        self.description = description
        self.version = version
        self.author = author
        self.category = category
        self.enabled = enabled
        self.path = path
        self.source = source  # "custom" (src/plugins/) or "store" (site-packages)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "category": self.category,
            "enabled": self.enabled,
            "path": self.path,
            "source": self.source,
        }


class PluginRegistry:
    """插件注册中心（单例）"""

    _instance: Optional["PluginRegistry"] = None

    def __init__(self):
        self._plugins: dict[str, PluginMeta] = {}
        self._plugin_dir: str = ""
        self._loaded = False

    @classmethod
    def get_instance(cls) -> "PluginRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── 插件发现 ──

    def discover(self, plugin_dir: str) -> list[PluginMeta]:
        """扫描插件目录，发现所有插件"""
        self._plugin_dir = plugin_dir
        self._plugins.clear()

        # 加载开关状态
        states = self._load_states()

        if not os.path.isdir(plugin_dir):
            logger.warning(f"插件目录不存在: {plugin_dir}")
            return []

        for item in sorted(os.listdir(plugin_dir)):
            item_path = os.path.join(plugin_dir, item)
            if not os.path.isdir(item_path):
                continue
            if item.startswith(".") or item.startswith("_"):
                continue

            init_file = os.path.join(item_path, "__init__.py")
            if not os.path.exists(init_file):
                continue

            meta = self._extract_meta(item, item_path)
            # 应用开关状态
            meta.enabled = states.get(meta.name, True)
            self._plugins[meta.name] = meta

        self._loaded = True
        logger.info(f"插件注册中心: 从本地目录发现 {len(self._plugins)} 个插件")
        return list(self._plugins.values())

    def discover_store_plugins(self) -> list["PluginMeta"]:
        """使用 Nonebot2 原生 API 发现官方商店插件（site-packages 中的插件）。

        在 discover() 之后调用，会将商店插件补充到注册表中（不会覆盖已有的自定义插件）。
        """
        try:
            from nonebot import get_loaded_plugins
            from nonebot.plugin.model import PluginMetadata as NBMetadata
        except ImportError as e:
            logger.warning(f"无法导入 Nonebot2 插件 API: {e}")
            return []

        loaded = get_loaded_plugins()
        added = 0

        for plugin in loaded:
            # 跳过子插件（父插件:子插件命名）、无 matcher 的插件、已存在的插件
            if plugin.parent_plugin is not None:
                continue
            if plugin.id_ in self._plugins:
                continue
            # 跳过 echo 内置插件
            if plugin.id_ == "echo":
                continue

            meta = self._extract_store_meta(plugin)
            # 应用已有的开关状态
            states = self._load_states()
            meta.enabled = states.get(meta.name, True)
            self._plugins[meta.name] = meta
            added += 1

        if added > 0:
            logger.info(f"插件注册中心: 从商店发现 {added} 个插件")
        return [p for p in self._plugins.values() if p.source == "store"]

    def _extract_store_meta(self, plugin) -> "PluginMeta":
        """从 Nonebot2 Plugin 对象中提取元数据"""
        name = plugin.id_
        desc = ""
        version = "0.1.0"
        author = ""
        category = "feature"

        # 获取插件路径
        import inspect
        path = ""
        try:
            if hasattr(plugin, "module") and plugin.module:
                module_file = inspect.getfile(plugin.module)
                path = module_file
        except Exception:
            pass

        # 从 PluginMetadata 读取元数据
        if plugin.metadata:
            nb_meta = plugin.metadata
            desc = nb_meta.description or desc
            if nb_meta.type:
                category = nb_meta.type
            author = nb_meta.extra.get("author", author) if nb_meta.extra else author
            if not version and nb_meta.extra and "version" in nb_meta.extra:
                version = nb_meta.extra["version"]

        # 自动推断分类（当元数据未提供时）
        if category == "feature" or not plugin.metadata or not plugin.metadata.type:
            if "library" in name or any(k in name for k in ["alconna", "localstore", "orm", "uninfo", "waiter", "argot", "htmlrender", "imageutils"]):
                category = "library"
            elif "tool" in name or any(k in name for k in ["apscheduler", "docs", "status"]):
                category = "tool"
            elif "skland" in name:
                category = "game"

        # 自动生成描述（当元数据未提供时）
        if not desc:
            desc = _auto_store_description(name)

        return PluginMeta(
            name=name,
            description=desc,
            version=version,
            author=author,
            category=category,
            enabled=True,
            path=path,
            source="store",
        )

    def _extract_meta(self, name: str, path: str) -> PluginMeta:
        """从插件包中提取元数据"""
        desc = ""
        version = "0.1.0"
        author = ""
        category = "feature"

        try:
            # 尝试导入并读取 __plugin_meta__
            spec = importlib.util.spec_from_file_location(
                f"{name}._meta", os.path.join(path, "__init__.py")
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)

                if hasattr(mod, "__plugin_meta__"):
                    meta = mod.__plugin_meta__
                    # 兼容 dict 和 PluginMetadata 对象
                    if isinstance(meta, dict):
                        desc = meta.get("description", desc)
                        version = meta.get("version", version)
                        author = meta.get("author", author)
                        category = meta.get("category", category)
                    else:
                        # PluginMetadata 对象
                        desc = meta.description or desc
                        version = meta.extra.get("version", version) if meta.extra else version
                        author = meta.extra.get("author", author) if meta.extra else author
                        category = meta.extra.get("category", category) if meta.extra else category

                # 回退：使用模块 docstring
                if not desc and hasattr(mod, "__doc__") and mod.__doc__:
                    desc = mod.__doc__.strip().split("\n")[0]
        except Exception as e:
            logger.debug(f"提取插件元数据失败 ({name}): {e}")

        # 自动推断分类
        if "admin" in name:
            category = "admin"
        elif any(k in name for k in ["asr", "tts", "multimodal", "sentiment", "memory", "dialog", "profile"]):
            category = "core"
        elif "webui" in name:
            category = "tool"

        # 自动生成描述
        if not desc:
            desc = _auto_description(name)

        return PluginMeta(
            name=name,
            description=desc,
            version=version,
            author=author,
            category=category,
            enabled=True,
            path=path,
        )

    # ── 开关管理 ──

    def toggle(self, name: str) -> Optional[bool]:
        """切换插件开关状态，返回新状态；插件不存在返回 None"""
        if name not in self._plugins:
            return None
        self._plugins[name].enabled = not self._plugins[name].enabled
        self._save_states()
        return self._plugins[name].enabled

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """设置插件开关状态"""
        if name not in self._plugins:
            return False
        self._plugins[name].enabled = enabled
        self._save_states()
        return True

    def get_disabled_plugins(self) -> list[str]:
        """获取被禁用的插件名列表（供 NoneBot 加载时过滤）"""
        return [m.name for m in self._plugins.values() if not m.enabled]

    def get_all(self) -> list[PluginMeta]:
        return list(self._plugins.values())

    def get(self, name: str) -> Optional[PluginMeta]:
        return self._plugins.get(name)

    # ── 统计 ──

    def stats(self) -> dict:
        total = len(self._plugins)
        enabled = sum(1 for m in self._plugins.values() if m.enabled)
        return {
            "total": total,
            "enabled": enabled,
            "disabled": total - enabled,
            "by_category": self._count_by_category(),
            "by_source": self._count_by_source(),
        }

    def _count_by_category(self) -> dict:
        counts: dict[str, int] = {}
        for m in self._plugins.values():
            counts[m.category] = counts.get(m.category, 0) + 1
        return counts

    def _count_by_source(self) -> dict:
        counts: dict[str, int] = {}
        for m in self._plugins.values():
            counts[m.source] = counts.get(m.source, 0) + 1
        return counts

    # ── 持久化 ──

    def _load_states(self) -> dict[str, bool]:
        """从文件加载开关状态"""
        if not os.path.exists(PLUGIN_STATES_FILE):
            return {}
        try:
            with open(PLUGIN_STATES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_states(self):
        """保存开关状态到文件"""
        os.makedirs(os.path.dirname(PLUGIN_STATES_FILE), exist_ok=True)
        states = {m.name: m.enabled for m in self._plugins.values()}
        try:
            with open(PLUGIN_STATES_FILE, "w", encoding="utf-8") as f:
                json.dump(states, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存插件状态失败: {e}")


def _auto_description(name: str) -> str:
    """根据插件名自动生成描述"""
    mapping = {
        "nonebot_plugin_asr": "语音识别 (ASR) — 基于 Whisper，支持中文及多语言",
        "nonebot_plugin_tts": "语音合成 (TTS) — 基于 VITS 模型，支持中文合成",
        "nonebot_plugin_memory": "记忆系统 — 短期/长期记忆存储、检索、遗忘管理",
        "nonebot_plugin_dialog": "对话管理 — 多轮对话上下文、会话超时管理",
        "nonebot_plugin_sentiment": "情感分析 — 识别用户情绪，调整回复策略",
        "nonebot_plugin_profile": "用户画像 — 从记忆中自动提取用户特征",
        "nonebot_plugin_multimodal": "多模态支持 — 图片消息处理与理解",
        "nonebot_plugin_admin": "管理员命令 — 状态查询、配置热重载、记忆管理",
        "nonebot_plugin_update_baisuwen": "核心插件 — 白苏文 Bot 主逻辑 (LLM + 人设 + 编排)",
        "nonebot_plugin_webui": "Web 管理后台 — 可视化配置、插件管理、记忆浏览",
        "nonebot_plugin_strongholdtools": "据点工具 — 游戏数据查询",
    }
    return mapping.get(name, f"{name} 插件")


def _auto_store_description(name: str) -> str:
    """根据商店插件名自动生成描述"""
    mapping = {
        "nonebot_plugin_alconna": "Alconna 命令解析框架 — 强大的命令创建与参数解析工具",
        "nonebot_plugin_apscheduler": "定时任务调度 — 基于 APScheduler，支持 cron/interval/date 触发器",
        "nonebot_plugin_argot": "暗语消息 — 临时消息存储与过期管理",
        "nonebot_plugin_docs": "在线文档 — 提供 Nonebot 官方文档本地浏览",
        "nonebot_plugin_htmlrender": "HTML 渲染 — 使用 Playwright 将 HTML/Markdown 渲染为图片",
        "nonebot_plugin_imageutils": "图片工具 — 图片创建、拼接、文字渲染",
        "nonebot_plugin_localstore": "本地存储 — 为插件提供标准化的本地文件存储路径",
        "nonebot_plugin_orm": "数据库 ORM — 基于 SQLAlchemy 的异步 ORM 与 Alembic 迁移",
        "nonebot_plugin_skland": "森空岛 — 查询明日方舟/终末地游戏数据（角色卡、签到、抽卡记录等）",
        "nonebot_plugin_status": "服务器状态 — 查看 CPU、内存、磁盘、Bot 运行时间等",
        "nonebot_plugin_uninfo": "通用用户信息 — 多平台统一的用户/群组信息获取接口",
        "nonebot_plugin_user": "用户管理 — 跨平台的用户绑定与管理",
        "nonebot_plugin_waiter": "等待器 — 多轮交互等待用户输入，支持超时、重试、验证",
    }
    return mapping.get(name, f"{name} 插件（商店）")


# 全局单例
registry = PluginRegistry.get_instance()
