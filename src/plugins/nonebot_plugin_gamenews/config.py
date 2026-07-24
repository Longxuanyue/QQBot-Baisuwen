"""
插件配置 —— 通过 .env 或环境变量注入。
"""

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


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
    urgency_hours: int = 48                      # 多少小时内算紧迫
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

    # ── HTTP（保留用于内部调用） ──
    request_delay: float = 1.0
    request_timeout: int = 30

    class Config:
        env_prefix = "GAMENEWS_"
        extra = "ignore"


plugin_config = PluginConfig()

# 设置默认路径：相对于本插件目录查找 tools/game-event-progress
_PLUGIN_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _PLUGIN_DIR.parent.parent.parent  # baisuwen/

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
