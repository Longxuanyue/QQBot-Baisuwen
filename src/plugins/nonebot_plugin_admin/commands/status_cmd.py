"""状态查询命令"""

import os
import sys
import time
import psutil

from nonebot import logger


async def handle_status() -> str:
    """生成系统状态报告"""
    lines = ["📊 系统状态报告", ""]

    # 基础信息
    process = psutil.Process()
    mem_info = process.memory_info()
    cpu_percent = process.cpu_percent(interval=0.1)

    lines.append("--- 进程 ---")
    lines.append(f"PID: {process.pid}")
    lines.append(f"CPU: {cpu_percent:.1f}%")
    lines.append(f"内存: {mem_info.rss / 1024 / 1024:.1f} MB")
    lines.append(f"运行时间: {time.time() - process.create_time():.0f}s")

    # 服务状态（如果 registry 可用）
    lines.append("")
    lines.append("--- 服务 ---")
    try:
        from ...nonebot_plugin_update_baisuwen.registry import registry
        for name, available in registry.status().items():
            status_icon = "✅" if available else "❌"
            lines.append(f"{status_icon} {name}")
    except Exception:
        lines.append("(服务注册中心不可用)")

    # 数据库状态
    lines.append("")
    lines.append("--- 数据 ---")
    try:
        from ...nonebot_plugin_update_baisuwen.config import plugin_config
        user_data_dir = plugin_config.memory.user_data_dir
    except Exception:
        user_data_dir = "user_data"
    if os.path.exists(user_data_dir):
        db_count = len([
            f for f in os.listdir(user_data_dir) if f.endswith(".db")
        ])
        total_size = sum(
            os.path.getsize(os.path.join(user_data_dir, f))
            for f in os.listdir(user_data_dir) if f.endswith(".db")
        )
        lines.append(f"用户数据库: {db_count} 个文件")
        lines.append(f"总大小: {total_size / 1024 / 1024:.1f} MB")
    else:
        lines.append("用户数据目录不存在")

    return "\n".join(lines)
