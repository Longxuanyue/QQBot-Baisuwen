"""
nonebot_plugin_webui — Web 管理后台插件

提供可视化 Bot 管理界面：仪表盘、插件管理、配置编辑、人设管理、
记忆浏览、审计日志、备份恢复。

挂载在 NoneBot 的 FastAPI 应用上，复用现有端口。
"""

__version__ = "1.0.2"

import os
import sys
from nonebot import get_driver, on_command, logger
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, Message
from nonebot.permission import SUPERUSER
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata

from .config import DATA_DIR, AUDIT_LOG_FILE
from .auth import token_store
from .audit import log_startup, log_action
from .plugin_registry import registry
from .memory_provider import memory_registry
from .restart import clear_restart_signal

# ── 插件元数据 ──

__plugin_meta__ = PluginMetadata(
    name="Web 管理后台",
    description="Web 管理后台 — 可视化配置、插件管理、人设编辑、记忆浏览、审计日志、备份恢复",
    usage="浏览器访问 http://127.0.0.1:42200/webui/ 进入后台；/auth <token> 完成登录验证",
    type="application",
    homepage="https://github.com/baisuwen",
    supported_adapters={"~onebot.v11"},
    extra={
        "author": "baisuwen",
        "version": __version__,
        "category": "tool",
    },
)

driver = get_driver()


# ── /auth 命令：WebUI 登录验证 ──

auth_cmd = on_command("auth", permission=SUPERUSER, priority=1, block=True)


@auth_cmd.handle()
async def handle_auth(bot: Bot, event: MessageEvent, arg: Message = CommandArg()):
    token = arg.extract_plain_text().strip()
    if not token:
        await auth_cmd.finish("请提供登录 Token，格式: /auth <token>")

    user_id = str(event.user_id)
    if token_store.verify(token, user_id):
        log_action(user_id, "login", detail="WebUI Token 验证成功")
        await auth_cmd.finish("✅ WebUI 登录已授权！请返回浏览器继续操作。")
    else:
        await auth_cmd.finish("❌ Token 无效、已过期或已使用。请刷新 WebUI 页面获取新 Token。")


# ── 启动与关闭 ──

@driver.on_startup
async def startup():
    """挂载 WebUI 到 NoneBot FastAPI 应用"""
    # 清除残留的重启信号
    clear_restart_signal()

    # 记录启动
    log_startup()

    # 确保 data 目录存在
    os.makedirs(DATA_DIR, exist_ok=True)

    # 扫描并注册本地插件（src/plugins/）
    plugin_dirs = _find_plugin_dir()
    if plugin_dirs:
        registry.discover(plugin_dirs)
    else:
        logger.warning("WebUI: 无法确定插件目录，插件管理功能受限")

    # 发现并注册官方商店插件（site-packages）
    registry.discover_store_plugins()

    # 挂载 WebUI 子应用
    try:
        from fastapi.staticfiles import StaticFiles
        app = _get_fastapi_app()
        from .server import webui_app

        # 挂载静态文件
        static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
        if os.path.isdir(static_dir):
            webui_app.mount("/static", StaticFiles(directory=static_dir), name="webui_static")
            logger.debug(f"WebUI 静态文件已挂载: {static_dir}")

        app.mount("/webui", webui_app)
        logger.info("WebUI 管理后台已挂载: http://127.0.0.1:{port}/webui/"
                     .format(port=os.getenv("PORT", "42200")))
    except Exception as e:
        logger.error(f"WebUI 挂载失败: {e}")

    # 挂载 WebSocket（需要 Starlette 支持）
    try:
        from .websocket import ws_manager
        app = _get_fastapi_app()
        @app.websocket("/webui/ws")
        async def ws_endpoint(websocket):
            await ws_manager.handle_connection(websocket)
        logger.info("WebUI WebSocket 端点已挂载: /webui/ws")
    except Exception as e:
        logger.warning(f"WebUI WebSocket 挂载失败（将使用 HTTP 轮询）: {e}")

    # 尝试注册记忆后端（如果记忆插件已加载）
    _try_register_memory_provider()

    # 将 webui 自身加入注册表
    from .plugin_registry import PluginMeta
    registry._plugins["nonebot_plugin_webui"] = PluginMeta(
        name="nonebot_plugin_webui",
        description=__plugin_meta__.description,
        version=__plugin_meta__.extra.get("version", ""),
        author=__plugin_meta__.extra.get("author", ""),
        category=__plugin_meta__.extra.get("category", ""),
        enabled=True,
        path=os.path.dirname(os.path.abspath(__file__)),
    )

    logger.info("nonebot_plugin_webui 已启动")


@driver.on_shutdown
async def shutdown():
    logger.info("nonebot_plugin_webui 已关闭")


def _find_plugin_dir() -> str:
    """查找插件目录"""
    current = os.path.dirname(os.path.abspath(__file__))
    # current: .../src/plugins/nonebot_plugin_webui
    plugins_dir = os.path.dirname(current)
    return plugins_dir if os.path.isdir(plugins_dir) else ""


def _get_fastapi_app():
    """获取 NoneBot 的 FastAPI 应用"""
    from nonebot import get_app
    return get_app()


def _try_register_memory_provider():
    """尝试从已加载的记忆插件中注册 MemoryProvider"""
    try:
        from ..nonebot_plugin_memory import user_manager as um
        from ..nonebot_plugin_memory import retrieval
        from ..nonebot_plugin_memory import db_init
        from .memory_provider import MemoryProvider, MemoryEntry, MemoryQueryResult, MemoryStats, memory_registry

        class SQLiteMemoryProvider(MemoryProvider):
            @property
            def provider_name(self) -> str:
                return "SQLite"

            def is_available(self) -> bool:
                return True

            async def get_all_users(self) -> list[str]:
                return um.UserMemoryManager.get_all_user_ids_static()

            async def get_memories(self, user_id, page=1, page_size=50, search=None):
                mgr = um.UserMemoryManager(user_id)
                try:
                    all_memories = mgr.get_all_memories(limit=5000)
                except Exception:
                    all_memories = []

                # 搜索过滤
                if search:
                    search_lower = search.lower()
                    all_memories = [
                        m for m in all_memories
                        if search_lower in m.get("content", "").lower()
                    ]

                total = len(all_memories)
                start = (page - 1) * page_size
                end = start + page_size
                page_entries = all_memories[start:end]

                entries = [
                    MemoryEntry(
                        # 前缀区分 short/long 数据库，避免 ID 冲突导致删错记忆
                        id=f"{e.get('type', 'short')}_{e.get('id', '')}",
                        content=e.get("content", ""),
                        importance=e.get("importance", 0.5),
                        strength=e.get("strength", 0.5),
                        access_count=e.get("access_count", 0),
                        last_accessed=str(e.get("last_accessed", "")),
                        source=e.get("type", "short"),
                        created_at="",
                    )
                    for e in page_entries
                ]

                return MemoryQueryResult(
                    entries=entries,
                    total=total,
                    page=page,
                    page_size=page_size,
                    user_id=user_id,
                )

            async def delete_memory(self, user_id, memory_id):
                try:
                    mgr = um.UserMemoryManager(user_id)
                    from ..nonebot_plugin_memory.explicit import delete_memory_by_id
                    # 解析带前缀的 ID：short_123 → 删短期库，long_456 → 删长期库
                    # 兼容旧格式（纯数字 ID，此时尝试两个库）
                    if memory_id.startswith("long_"):
                        return delete_memory_by_id(int(memory_id[5:]), mgr.long_db)
                    elif memory_id.startswith("short_"):
                        return delete_memory_by_id(int(memory_id[6:]), mgr.short_db)
                    else:
                        # 兼容旧格式：尝试两个库
                        r1 = delete_memory_by_id(int(memory_id), mgr.short_db)
                        r2 = delete_memory_by_id(int(memory_id), mgr.long_db)
                        return r1 or r2
                except Exception:
                    return False

            async def delete_all_memories(self, user_id):
                try:
                    mgr = um.UserMemoryManager(user_id)
                    from ..nonebot_plugin_memory.explicit import clear_all_memories
                    c1 = clear_all_memories(mgr.short_db)
                    c2 = clear_all_memories(mgr.long_db)
                    return c1 + c2
                except Exception:
                    return 0

            async def get_stats(self, user_id):
                import sqlite3
                stats = MemoryStats(user_id=user_id)
                try:
                    for db_type, db_path in [("short", um.get_user_db_paths(user_id)[0]),
                                              ("long", um.get_user_db_paths(user_id)[1])]:
                        if not os.path.exists(db_path):
                            continue
                        conn = sqlite3.connect(db_path)
                        cur = conn.cursor()
                        cur.execute(
                            "SELECT COUNT(*), AVG(importance), AVG(strength), MAX(access_count) "
                            "FROM memories"
                        )
                        count, avg_imp, avg_str, max_acc = cur.fetchone()
                        conn.close()
                        if db_type == "short":
                            stats.short_count = count or 0
                        else:
                            stats.long_count = count or 0
                        stats.total_count += count or 0
                        if avg_imp:
                            stats.avg_importance = max(stats.avg_importance, avg_imp)
                        if avg_str:
                            stats.avg_strength = max(stats.avg_strength, avg_str)
                        if max_acc:
                            stats.max_access_count = max(stats.max_access_count, max_acc)
                except Exception:
                    pass
                return stats

            async def export_all(self):
                users = await self.get_all_users()
                data = {}
                for uid in users:
                    mgr = um.UserMemoryManager(uid)
                    data[uid] = mgr.get_all_memories(limit=10000)
                return {"users": data}

        # 给 UserMemoryManager 添加静态方法（如果不存在）
        if not hasattr(um.UserMemoryManager, 'get_all_user_ids_static'):
            @staticmethod
            def _get_all_user_ids_static():
                import glob as _glob
                user_data_dir = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                    "user_data"
                )
                if not os.path.isdir(user_data_dir):
                    return []
                ids = set()
                for f in _glob.glob(os.path.join(user_data_dir, "short_*.db")):
                    base = os.path.basename(f)
                    uid = base[6:-3]
                    ids.add(uid)
                return sorted(ids)
            um.UserMemoryManager.get_all_user_ids_static = _get_all_user_ids_static

        memory_registry.register(SQLiteMemoryProvider())
        logger.info("WebUI: SQLiteMemoryProvider 已注册")

    except ImportError as e:
        logger.debug(f"WebUI: 记忆插件未加载，跳过 MemoryProvider 注册 ({e})")
    except Exception as e:
        logger.warning(f"WebUI: MemoryProvider 注册失败: {e}")
