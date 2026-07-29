"""
插件配置 —— 通过 .env 或环境变量注入。
"""

import os
from pathlib import Path

from pydantic_settings import BaseSettings

# 项目根目录（baisuwen/）
_PLUGIN_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _PLUGIN_DIR.parent.parent.parent

# 显式加载 .env 到 os.environ，避免因插件导入顺序导致配置为空
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(_PROJECT_ROOT, ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path, override=False)
except ImportError:
    pass


class PluginConfig(BaseSettings):
    """nonebot_plugin_gamenews 配置"""

    enabled: bool = True

    # ── 数据源路径 ──
    game_event_data_dir: str = ""       # game-event-progress 的 data/ 目录
    game_event_scripts_dir: str = ""    # game-event-progress 的 scripts/ 目录
    game_event_covers_dir: str = ""     # game-event-progress 的 public/covers/ 目录

    # ── 定时任务 ──
    cron_hour: int = 8
    cron_minute: int = 0
    push_hour: int = 8
    push_minute: int = 30

    # ── 紧迫提醒 ──
    urgency_hours: int = 48                       # 多少小时内算紧迫
    urgency_cron_hours: list[int] = [10, 20]     # 紧迫提醒时间点（每小时整点触发）

    # ── 数据库（订阅） ──
    db_path: str = ""

    @property
    def db_dir_path(self) -> str:
        return str(Path(self.db_path).parent) if self.db_path else ""

    # ── 推送目标 ──
    target_groups: list[str] = []
    target_users: list[str] = []

    # ── 渲染 ──
    render_width: int = 780
    device_scale_factor: float = 2.0

    # ── HTTP ──
    request_delay: float = 1.0
    request_timeout: int = 30

    class Config:
        env_prefix = "GAMENEWS_"
        extra = "ignore"


plugin_config = PluginConfig()

# ── 兼容旧 .env 键名 ──
_crawl_val = os.getenv("GAMENEWS_CRAWL_HOURS", "")
if _crawl_val and plugin_config.urgency_hours == 48:
    plugin_config.urgency_hours = int(_crawl_val)

# 设置默认路径：相对于本插件目录查找 tools/game-event-progress
if not plugin_config.game_event_data_dir:
    plugin_config.game_event_data_dir = str(
        _PROJECT_ROOT / "tools" / "game-event-progress" / "data"
    )
if not plugin_config.game_event_scripts_dir:
    plugin_config.game_event_scripts_dir = str(
        _PROJECT_ROOT / "tools" / "game-event-progress" / "scripts"
    )
if not plugin_config.game_event_covers_dir:
    plugin_config.game_event_covers_dir = str(
        _PROJECT_ROOT / "tools" / "game-event-progress" / "public" / "covers"
    )
if not plugin_config.db_path:
    plugin_config.db_path = str(_PLUGIN_DIR / "data" / "gamenews.db")
