"""
WebUI 服务端：FastAPI 子应用 + 全部路由
"""

import json
import os
import re
import sys
import time
import asyncio
from typing import Optional

from fastapi import FastAPI, Request, Response, Cookie
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from nonebot import logger

from . import config as cfg
from .auth import (
    token_store, create_session, verify_session,
    get_user_role, check_permission, get_role_permissions,
    save_users_file,
)
from .audit import log_action, query_logs, get_last_startup_time, log_startup
from .backup import create_backup, restore_backup
from .memory_provider import memory_registry
from .plugin_registry import registry
from .restart import request_restart, schedule_restart_exit, get_restart_script


# ── FastAPI 子应用 ──

webui_app = FastAPI(title="白苏文 Bot 管理后台", version="1.0.0")

# Jinja2 模板
_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
templates = Jinja2Templates(directory=_TEMPLATE_DIR)


# ── 全局模板变量 ──

def _base_context(request: Request, user_id: str = "") -> dict:
    """构建模板基础上下文"""
    role = get_user_role(user_id) if user_id else ""
    permissions = get_role_permissions(role)
    # 生成侧边栏菜单项
    nav = [
        {"href": "/webui/dashboard", "label": "仪表盘", "icon": "📊",
         "perm": "dashboard.view"},
        {"href": "/webui/plugins", "label": "插件管理", "icon": "🧩",
         "perm": "plugins.view"},
        {"href": "/webui/config", "label": "配置管理", "icon": "⚙️",
         "perm": "config.view"},
        {"href": "/webui/personality", "label": "人设管理", "icon": "🎭",
         "perm": "personality.view"},
        {"href": "/webui/memory", "label": "记忆浏览", "icon": "🧠",
         "perm": "memory.view"},
        {"href": "/webui/backup", "label": "备份恢复", "icon": "💾",
         "perm": "backup.download"},
    ]
    # super 独有
    if "audit.view" in permissions:
        nav.append(
            {"href": "/webui/audit", "label": "审计日志", "icon": "📋",
             "perm": "audit.view"},
        )

    return {
        "request": request,
        "user_id": user_id,
        "role": role,
        "nav": [n for n in nav if n["perm"] in permissions],
        "has_restart_pending": os.path.exists(
            os.path.join(cfg.DATA_DIR, ".restart_signal")
        ),
    }


# ── 认证依赖 ──

def _get_user(request: Request) -> str:
    """从 Cookie 中提取已验证的 user_id，失败返回空字符串"""
    session = request.cookies.get("webui_session", "")
    if not session:
        return ""
    user_id = verify_session(session)
    return user_id or ""


def _require_auth(request: Request) -> str:
    """要求登录，未登录返回空"""
    return _get_user(request)


def _require_perm(request: Request, action: str) -> str:
    """要求特定权限，无权限返回空"""
    user_id = _get_user(request)
    if not user_id:
        return ""
    if not check_permission(user_id, action):
        return ""
    return user_id


def _get_client_ip(request: Request) -> str:
    """获取客户端 IP"""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


# ── 页面路由 ──

@webui_app.get("/", response_class=HTMLResponse)
async def page_root(request: Request):
    return RedirectResponse(url="/webui/dashboard")


@webui_app.get("/login", response_class=HTMLResponse)
async def page_login(request: Request):
    """登录页"""
    token = token_store.create()
    return templates.TemplateResponse(request, "login.html", {
        "token": token,
        "ws_url": f"/webui/ws",
    })


@webui_app.get("/dashboard", response_class=HTMLResponse)
async def page_dashboard(request: Request):
    """仪表盘"""
    user_id = _require_perm(request, "dashboard.view")
    if not user_id:
        return RedirectResponse(url="/webui/login")
    ctx = _base_context(request, user_id)

    # 系统信息
    import psutil
    import platform
    from nonebot import get_driver

    process = psutil.Process()
    mem_info = process.memory_info()
    last_startup = get_last_startup_time()

    # 计算运行天数
    uptime_days = 0
    uptime_hours = 0
    if last_startup:
        try:
            start = time.mktime(time.strptime(last_startup, "%Y-%m-%dT%H:%M:%S"))
            uptime_seconds = time.time() - start
            uptime_days = int(uptime_seconds // 86400)
            uptime_hours = int((uptime_seconds % 86400) // 3600)
        except Exception:
            pass

    # Bot 在线状态
    bot_online = False
    try:
        driver = get_driver()
        bot_online = len(driver.bots) > 0
    except Exception:
        pass

    # Python / NoneBot 版本
    try:
        import nonebot
        nb_version = nonebot.__version__
    except Exception:
        nb_version = "unknown"

    # CPU 使用率：interval=None 使用缓存值（非阻塞），首次返回 0.0
    cpu_val = process.cpu_percent(interval=None)
    if cpu_val == 0.0:
        # 首次访问时用 psutil 系统级 CPU（也是非阻塞）
        cpu_val = psutil.cpu_percent(interval=None)
    # 用户计数：异步获取，超时 1s 兜底（不阻塞页面渲染）
    user_count = await _count_memory_users_async()

    ctx.update({
        "active_page": "dashboard",
        "sys_info": {
            "python_version": platform.python_version(),
            "nonebot_version": nb_version,
            "platform": platform.system(),
            "pid": process.pid,
            "cpu": f"{cpu_val:.1f}",
            "mem_mb": f"{mem_info.rss / 1024 / 1024:.1f}",
            "uptime_days": uptime_days,
            "uptime_hours": uptime_hours,
            "last_startup": last_startup or "未知",
            "bot_online": bot_online,
        },
        "plugin_stats": registry.stats(),
        "user_count": user_count,
    })
    return templates.TemplateResponse(request, "dashboard.html", ctx)


@webui_app.get("/plugins", response_class=HTMLResponse)
async def page_plugins(request: Request):
    """插件管理页"""
    user_id = _require_perm(request, "plugins.view")
    if not user_id:
        return RedirectResponse(url="/webui/login")
    ctx = _base_context(request, user_id)
    ctx.update({
        "active_page": "plugins",
        "plugins": [p.to_dict() for p in registry.get_all()],
        "can_toggle": "plugins.toggle" in get_role_permissions(get_user_role(user_id)),
        "stats": registry.stats(),
    })
    return templates.TemplateResponse(request, "plugins.html", ctx)


@webui_app.get("/config", response_class=HTMLResponse)
async def page_config(request: Request):
    """配置管理页"""
    user_id = _require_perm(request, "config.view")
    if not user_id:
        return RedirectResponse(url="/webui/login")
    ctx = _base_context(request, user_id)
    can_edit = "config.edit" in get_role_permissions(get_user_role(user_id))

    # 读取 .env
    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        ".env"
    )
    env_content = ""
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            env_content = f.read()

    ctx.update({
        "active_page": "config",
        "env_content": env_content,
        "can_edit": can_edit,
    })
    return templates.TemplateResponse(request, "config_env.html", ctx)


@webui_app.get("/personality", response_class=HTMLResponse)
async def page_personality(request: Request):
    """人设管理页"""
    user_id = _require_perm(request, "personality.view")
    if not user_id:
        return RedirectResponse(url="/webui/login")
    ctx = _base_context(request, user_id)
    can_edit = "personality.edit" in get_role_permissions(get_user_role(user_id))

    personality_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "src/plugins/nonebot_plugin_update_baisuwen/personality_traits.json"
    )
    personality_content = ""
    if os.path.exists(personality_path):
        with open(personality_path, "r", encoding="utf-8") as f:
            personality_content = f.read()

    ctx.update({
        "active_page": "personality",
        "personality_content": personality_content,
        "can_edit": can_edit,
    })
    return templates.TemplateResponse(request, "personality.html", ctx)


@webui_app.get("/memory", response_class=HTMLResponse)
async def page_memory(request: Request):
    """记忆浏览页"""
    user_id = _require_perm(request, "memory.view")
    if not user_id:
        return RedirectResponse(url="/webui/login")
    ctx = _base_context(request, user_id)
    role = get_user_role(user_id)
    permissions = get_role_permissions(role)
    users = []
    if memory_registry.has_provider:
        provider = memory_registry.get()
        users = await provider.get_all_users()

    ctx.update({
        "active_page": "memory",
        "users": users,
        "can_delete": "memory.delete" in permissions,
        "can_clear": "memory.clear" in permissions,
        "has_provider": memory_registry.has_provider,
    })
    return templates.TemplateResponse(request, "memory_viewer.html", ctx)


@webui_app.get("/audit", response_class=HTMLResponse)
async def page_audit(request: Request):
    """审计日志页"""
    user_id = _require_perm(request, "audit.view")
    if not user_id:
        return RedirectResponse(url="/webui/login")
    ctx = _base_context(request, user_id)
    ctx.update({"active_page": "audit"})
    return templates.TemplateResponse(request, "audit_log.html", ctx)


@webui_app.get("/backup", response_class=HTMLResponse)
async def page_backup(request: Request):
    """备份恢复页"""
    user_id = _require_perm(request, "backup.download")
    if not user_id:
        return RedirectResponse(url="/webui/login")

    # 列出已有备份
    backups = []
    if os.path.isdir(cfg.ENV_BACKUP_DIR):
        for f in sorted(os.listdir(cfg.ENV_BACKUP_DIR), reverse=True):
            fpath = os.path.join(cfg.ENV_BACKUP_DIR, f)
            backups.append({
                "name": f,
                "size": f"{os.path.getsize(fpath) / 1024:.1f} KB",
                "time": time.strftime(
                    "%Y-%m-%d %H:%M:%S",
                    time.localtime(os.path.getmtime(fpath))
                ),
            })

    ctx = _base_context(request, user_id)
    permissions = get_role_permissions(get_user_role(user_id))
    ctx.update({
        "active_page": "backup",
        "backups": backups[:20],
        "can_restore": "backup.restore" in permissions,
    })
    return templates.TemplateResponse(request, "backup.html", ctx)


# ── API 路由 ──

@webui_app.post("/api/auth/status")
async def api_auth_status(request: Request):
    """轮询 Token 验证状态"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    token = body.get("token", "")
    result = token_store.check(token)
    if result is not None:
        session = create_session(result["user_id"])
        log_action(
            result["user_id"], "login",
            detail="WebUI 登录成功",
            ip=_get_client_ip(request),
        )
        return JSONResponse({
            "ok": True,
            "session": session,
            "user_id": result["user_id"],
        })
    return JSONResponse({"ok": False})


@webui_app.get("/api/dashboard")
async def api_dashboard(request: Request):
    """仪表盘 JSON 数据"""
    user_id = _require_perm(request, "dashboard.view")
    if not user_id:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    return JSONResponse({
        "plugin_stats": registry.stats(),
        "user_count": await _count_memory_users_async(),
    })


@webui_app.get("/api/plugins")
async def api_plugins(request: Request):
    """获取全部插件列表"""
    user_id = _require_perm(request, "plugins.view")
    if not user_id:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    return JSONResponse({
        "plugins": [p.to_dict() for p in registry.get_all()],
        "stats": registry.stats(),
    })


@webui_app.post("/api/plugins/{name}/toggle")
async def api_plugin_toggle(request: Request, name: str):
    """切换插件开关"""
    user_id = _require_perm(request, "plugins.toggle")
    if not user_id:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    new_state = registry.toggle(name)
    if new_state is None:
        return JSONResponse({"error": "plugin not found"}, status_code=404)

    log_action(
        user_id, "plugin.toggle", target=name,
        detail="启用" if new_state else "禁用",
        ip=_get_client_ip(request),
    )

    return JSONResponse({
        "ok": True,
        "name": name,
        "enabled": new_state,
        "needs_restart": True,
    })


@webui_app.get("/api/config")
async def api_config_get(request: Request):
    """读取 .env 内容"""
    user_id = _require_perm(request, "config.view")
    if not user_id:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    env_path = os.path.join(root, ".env")
    if not os.path.exists(env_path):
        return JSONResponse({"content": "", "message": ".env 文件不存在"})

    with open(env_path, "r", encoding="utf-8") as f:
        content = f.read()

    return JSONResponse({"content": content})


@webui_app.post("/api/config")
async def api_config_save(request: Request):
    """保存 .env 配置"""
    user_id = _require_perm(request, "config.edit")
    if not user_id:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    new_content = body.get("content", "")

    # 格式校验
    errors = _validate_env(new_content)
    if errors:
        return JSONResponse({"ok": False, "error": "格式校验失败", "details": errors})

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    env_path = os.path.join(root, ".env")

    # 备份 + 原子写入
    from .backup import _backup_file
    _backup_file(env_path)

    tmp_path = env_path + ".new"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        os.replace(tmp_path, env_path)
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return JSONResponse({"ok": False, "error": f"写入失败: {e}"})

    log_action(
        user_id, "config.save",
        detail=f"修改了 .env 配置",
        ip=_get_client_ip(request),
    )

    return JSONResponse({
        "ok": True,
        "message": "配置已保存，需要重启 Bot 才能生效",
        "needs_restart": True,
    })


@webui_app.get("/api/personality")
async def api_personality_get(request: Request):
    """读取人设 JSON"""
    user_id = _require_perm(request, "personality.view")
    if not user_id:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    personality_path = os.path.join(
        root, "src/plugins/nonebot_plugin_update_baisuwen/personality_traits.json"
    )
    if not os.path.exists(personality_path):
        return JSONResponse({"content": "{}", "message": "人设文件不存在"})

    with open(personality_path, "r", encoding="utf-8") as f:
        content = f.read()

    return JSONResponse({"content": content})


@webui_app.post("/api/personality")
async def api_personality_save(request: Request):
    """保存人设 JSON"""
    user_id = _require_perm(request, "personality.edit")
    if not user_id:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    new_content = body.get("content", "")

    # JSON 格式校验
    try:
        json.loads(new_content)
    except json.JSONDecodeError as e:
        return JSONResponse({"ok": False, "error": f"JSON 格式错误: {e}"})

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    personality_path = os.path.join(
        root, "src/plugins/nonebot_plugin_update_baisuwen/personality_traits.json"
    )

    # 备份 + 写入
    from .backup import _backup_file
    _backup_file(personality_path)

    try:
        with open(personality_path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"写入失败: {e}"})

    # 热重载人设
    try:
        from nonebot_plugin_update_baisuwen.personality import reload_personality
        reload_personality()
    except Exception as e:
        logger.warning(f"人设热重载失败: {e}")

    log_action(
        user_id, "personality.save",
        detail="修改了人设配置",
        ip=_get_client_ip(request),
    )

    return JSONResponse({"ok": True, "message": "人设已保存并热重载"})


@webui_app.get("/api/memory/users")
async def api_memory_users(request: Request):
    """获取所有有记忆的用户"""
    user_id = _require_perm(request, "memory.view")
    if not user_id:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    if not memory_registry.has_provider:
        return JSONResponse({"users": [], "message": "记忆后端未注册"})

    provider = memory_registry.get()
    users = await provider.get_all_users()
    # 获取每个用户的统计
    user_stats = []
    for uid in users:
        stats = await provider.get_stats(uid)
        user_stats.append({
            "user_id": uid,
            "short_count": stats.short_count,
            "long_count": stats.long_count,
            "total_count": stats.total_count,
        })

    return JSONResponse({"users": user_stats})


@webui_app.get("/api/memory/{user_id}")
async def api_memory_get(
    request: Request,
    user_id: str,
    page: int = 1,
    page_size: int = 50,
    search: str = "",
):
    """分页获取用户记忆"""
    webui_user = _require_perm(request, "memory.view")
    if not webui_user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    if not memory_registry.has_provider:
        return JSONResponse({"error": "记忆后端未注册"}, status_code=500)

    provider = memory_registry.get()
    result = await provider.get_memories(
        user_id,
        page=page,
        page_size=page_size,
        search=search if search else None,
    )

    return JSONResponse({
        "entries": [
            {
                "id": e.id,
                "content": e.content,
                "importance": e.importance,
                "strength": e.strength,
                "access_count": e.access_count,
                "last_accessed": e.last_accessed,
                "source": e.source,
                "created_at": e.created_at,
            }
            for e in result.entries
        ],
        "total": result.total,
        "page": result.page,
        "page_size": result.page_size,
        "user_id": result.user_id,
    })


@webui_app.delete("/api/memory/{user_id}/{memory_id}")
async def api_memory_delete(request: Request, user_id: str, memory_id: str):
    """删除单条记忆"""
    webui_user = _require_perm(request, "memory.delete")
    if not webui_user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    if not memory_registry.has_provider:
        return JSONResponse({"error": "记忆后端未注册"}, status_code=500)

    provider = memory_registry.get()
    ok = await provider.delete_memory(user_id, memory_id)

    log_action(
        webui_user, "memory.delete",
        target=f"user={user_id}",
        detail=f"删除记忆 {memory_id}",
        ip=_get_client_ip(request),
    )

    return JSONResponse({"ok": ok})


@webui_app.delete("/api/memory/{user_id}")
async def api_memory_clear(request: Request, user_id: str):
    """清空用户全部记忆"""
    webui_user = _require_perm(request, "memory.clear")
    if not webui_user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    if not memory_registry.has_provider:
        return JSONResponse({"error": "记忆后端未注册"}, status_code=500)

    provider = memory_registry.get()
    count = await provider.delete_all_memories(user_id)

    log_action(
        webui_user, "memory.clear",
        target=f"user={user_id}",
        detail=f"清空 {count} 条记忆",
        ip=_get_client_ip(request),
    )

    return JSONResponse({"ok": True, "deleted": count})


@webui_app.get("/api/audit")
async def api_audit_query(
    request: Request,
    limit: int = 200,
    offset: int = 0,
    action: str = "",
    user: str = "",
    date_from: str = "",
    date_to: str = "",
):
    """查询审计日志"""
    webui_user = _require_perm(request, "audit.view")
    if not webui_user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    result = query_logs(
        limit=limit,
        offset=offset,
        action_filter=action,
        user_filter=user,
        date_from=date_from,
        date_to=date_to,
    )
    return JSONResponse(result)


@webui_app.post("/api/restart")
async def api_restart(request: Request):
    """重启 Bot"""
    user_id = _require_perm(request, "bot.restart")
    if not user_id:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    # 二次确认由前端完成，API 收到即执行
    log_action(
        user_id, "bot.restart",
        detail="通过 WebUI 请求重启",
        ip=_get_client_ip(request),
    )

    success = request_restart()
    if success:
        # 3 秒后退出进程（exit code 42），看门狗脚本会检测到此码并自动重启
        schedule_restart_exit(delay=3.0)
        return JSONResponse({
            "ok": True,
            "message": "重启信号已发出，Bot 将在 3 秒后退出",
        })
    else:
        return JSONResponse({
            "ok": False,
            "error": "无法写入重启信号文件",
        })


@webui_app.get("/api/restart/script")
async def api_restart_script(request: Request):
    """下载看门狗启动脚本（Windows .bat）"""
    user_id = _require_perm(request, "bot.restart")
    if not user_id:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    script = get_restart_script()
    return Response(
        content=script,
        media_type="application/x-bat",
        headers={"Content-Disposition": "attachment; filename=start_bot.bat"},
    )


@webui_app.get("/api/backup/download")
async def api_backup_download(request: Request, include_memory: bool = False):
    """下载备份包"""
    user_id = _require_perm(request, "backup.download")
    if not user_id:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    buf = create_backup(include_memory=include_memory)
    if buf is None:
        return JSONResponse({"error": "创建备份失败"}, status_code=500)

    log_action(
        user_id, "backup.download",
        detail=f"下载备份 (记忆数据={'是' if include_memory else '否'})",
        ip=_get_client_ip(request),
    )

    ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=baisuwen_backup_{ts}.zip"},
    )


@webui_app.post("/api/backup/restore")
async def api_backup_restore(request: Request):
    """上传恢复包"""
    user_id = _require_perm(request, "backup.restore")
    if not user_id:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        body = await request.body()
    except Exception:
        return JSONResponse({"error": "无法读取上传文件"}, status_code=400)

    result = restore_backup(body)

    if result["ok"]:
        log_action(
            user_id, "backup.restore",
            detail=f"恢复 {len(result['restored_files'])} 个文件",
            ip=_get_client_ip(request),
        )

    return JSONResponse(result)


# ── 用户管理 API ──

@webui_app.get("/api/users")
async def api_users_get(request: Request):
    """获取用户角色列表（仅 super）"""
    user_id = _require_perm(request, "users.manage")
    if not user_id:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    users = _load_users_file_with_super()
    return JSONResponse(users)


@webui_app.post("/api/users")
async def api_users_save(request: Request):
    """保存用户角色（仅 super）"""
    user_id = _require_perm(request, "users.manage")
    if not user_id:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    save_users_file(body)
    log_action(
        user_id, "users.manage",
        detail="修改了用户角色配置",
        ip=_get_client_ip(request),
    )
    return JSONResponse({"ok": True})


def _load_users_file_with_super() -> dict:
    """加载用户文件并注入 super users"""
    from .auth import _parse_superusers, _load_users_file
    users = _load_users_file()
    users["super"] = list(_parse_superusers())
    return users


# ── 辅助函数 ──

def _validate_env(content: str) -> list[str]:
    """校验 .env 内容格式，返回错误列表"""
    errors = []
    for i, line in enumerate(content.split("\n"), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            errors.append(f"第 {i} 行: 不是有效的 KEY=VALUE 格式")
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if not re.match(r'^[A-Z_][A-Z0-9_]*$', key):
            errors.append(f"第 {i} 行: KEY 格式无效 ({key})，只允许大写字母、数字、下划线")
    return errors


def _count_memory_users() -> int:
    """统计有记忆数据的用户数（同步版本，供非异步上下文调用）"""
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                _count_memory_users_async(), loop
            )
            return future.result(timeout=2)
        else:
            return loop.run_until_complete(_count_memory_users_async())
    except Exception:
        return 0


async def _count_memory_users_async() -> int:
    """统计有记忆数据的用户数（异步版本，带 1s 超时兜底）"""
    if not memory_registry.has_provider:
        return 0
    try:
        provider = memory_registry.get()
        users = await asyncio.wait_for(provider.get_all_users(), timeout=1.0)
        return len(users)
    except (asyncio.TimeoutError, Exception):
        return 0
