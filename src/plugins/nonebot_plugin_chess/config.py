"""国际象棋插件配置。

所有配置项以 ``CHESS_`` 为前缀（见 .env.example）。模块导入时手动加载
项目 .env（与项目其他独立插件约定一致），默认值可直接用于单元测试。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load_project_env() -> None:
    """加载项目 .env 与当前环境的 .env.<ENVIRONMENT>（不覆盖已有变量）。"""
    base = PROJECT_ROOT / ".env"
    if base.exists():
        load_dotenv(base, override=False)
    env_name = os.environ.get("ENVIRONMENT", "dev")
    extra = PROJECT_ROOT / f".env.{env_name}"
    if extra.exists():
        load_dotenv(extra, override=False)


@dataclass(slots=True)
class ChessSettings:
    """国际象棋插件设置（运行期由 CHESS_* 环境变量覆盖）。"""

    #: Stockfish 可执行文件路径；留空则使用内置纯 Python 引擎
    stockfish_path: str = ""
    #: 练习局默认先手（white/black）
    default_color: str = "white"
    #: 练习局默认难度（简单/普通/困难）
    default_difficulty: str = "普通"
    #: 对局无操作多少秒后判定超时结束
    game_expire_seconds: int = 1800
    #: 新玩家初始段位分
    rating_initial: int = 1200
    #: 常规对局 K 因子
    rating_k: int = 32
    #: 定级期（前 N 局）K 因子
    rating_k_provisional: int = 48
    #: 定级期对局数
    rating_provisional_games: int = 5
    #: 段位分下限
    rating_floor: int = 100
    #: 排行榜展示人数
    leaderboard_size: int = 20


@lru_cache(maxsize=1)
def get_settings() -> ChessSettings:
    """获取配置（首次调用时加载项目 .env 并读取 CHESS_* 变量）。"""
    _load_project_env()
    return ChessSettings(
        stockfish_path=os.environ.get("CHESS_STOCKFISH_PATH", ""),
        default_color=os.environ.get("CHESS_DEFAULT_COLOR", "white"),
        default_difficulty=os.environ.get("CHESS_DEFAULT_DIFFICULTY", "普通"),
        game_expire_seconds=int(os.environ.get("CHESS_GAME_EXPIRE_SECONDS", "1800")),
        rating_initial=int(os.environ.get("CHESS_RATING_INITIAL", "1200")),
        rating_k=int(os.environ.get("CHESS_RATING_K", "32")),
        rating_k_provisional=int(os.environ.get("CHESS_RATING_K_PROVISIONAL", "48")),
        rating_provisional_games=int(
            os.environ.get("CHESS_RATING_PROVISIONAL_GAMES", "5")
        ),
        rating_floor=int(os.environ.get("CHESS_RATING_FLOOR", "100")),
        leaderboard_size=int(os.environ.get("CHESS_LEADERBOARD_SIZE", "20")),
    )
