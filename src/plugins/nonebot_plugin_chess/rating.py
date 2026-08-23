"""段位分（Elo）与排行榜存储。

- 段位分采用国际象棋标准 Elo 评分：初始 ``rating_initial`` 分，每场计分
  对局后按 ``新分 = 旧分 + K * (得分 - 期望胜率)`` 结算（胜 1.0 / 和 0.5 / 负 0.0）。
- 前 ``rating_provisional_games`` 局为定级期，K 因子更大以快速收敛。
- 只展示分数（不划分段位名）；额外记录玩家挑战过的最高对手分与最高击败分。
- 排行榜数据存 SQLite（data/chess_rank.db），按分数降序排名。
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from .config import get_settings

_PROJECT_ROOT = Path(__file__).resolve().parents[3]

_COLUMNS = (
    "user_id",
    "nickname",
    "rating",
    "games",
    "wins",
    "draws",
    "losses",
    "max_challenged",
    "max_beaten",
    "updated_at",
)


@dataclass(slots=True)
class PlayerRecord:
    """排行榜单条记录（字段顺序与数据库表一致）。"""

    user_id: str
    nickname: str
    rating: int
    games: int
    wins: int
    draws: int
    losses: int
    max_challenged: int
    max_beaten: int
    updated_at: float

    @property
    def provisional(self) -> bool:
        """是否仍处于定级期（按初始分展示）。"""
        return self.games < get_settings().rating_provisional_games


def expected_score(player_rating: int, opponent_rating: int) -> float:
    """Elo 期望胜率（0~1）。"""
    return 1.0 / (1.0 + 10 ** ((opponent_rating - player_rating) / 400.0))


def new_rating(
    player_rating: int, opponent_rating: int, score: float, games: int
) -> int:
    """计算对局后的新段位分。"""
    settings = get_settings()
    if games < settings.rating_provisional_games:
        k = settings.rating_k_provisional
    else:
        k = settings.rating_k
    delta = round(k * (score - expected_score(player_rating, opponent_rating)))
    return max(settings.rating_floor, player_rating + delta)


def _db_path() -> Path:
    return _PROJECT_ROOT / "data" / "chess_rank.db"


def _connect() -> sqlite3.Connection:
    db = _db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS players ("
        "user_id TEXT PRIMARY KEY,"
        "nickname TEXT NOT NULL DEFAULT '',"
        "rating INTEGER NOT NULL DEFAULT 0,"
        "games INTEGER NOT NULL DEFAULT 0,"
        "wins INTEGER NOT NULL DEFAULT 0,"
        "draws INTEGER NOT NULL DEFAULT 0,"
        "losses INTEGER NOT NULL DEFAULT 0,"
        "max_challenged INTEGER NOT NULL DEFAULT 0,"
        "max_beaten INTEGER NOT NULL DEFAULT 0,"
        "updated_at REAL NOT NULL)"
    )
    return conn


def _row_to_record(row: tuple) -> PlayerRecord:
    return PlayerRecord(*row)


def get_record(user_id: str) -> PlayerRecord | None:
    """读取玩家记录；未打过计分对局返回 None。"""
    conn = _connect()
    try:
        row = conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM players WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()
    return _row_to_record(row) if row else None


def ensure_record(user_id: str, nickname: str = "") -> PlayerRecord:
    """获取记录，不存在则创建（初始分，不入库，仅内存返回）。"""
    record = get_record(user_id)
    if record is not None:
        return record
    settings = get_settings()
    return PlayerRecord(
        user_id=user_id,
        nickname=nickname,
        rating=settings.rating_initial,
        games=0,
        wins=0,
        draws=0,
        losses=0,
        max_challenged=0,
        max_beaten=0,
        updated_at=time.time(),
    )


def record_result(
    user_id: str, nickname: str, opponent_rating: int, score: float
) -> tuple[int, int]:
    """记录一场计分对局，返回 (段位分变化, 新段位分)。

    Args:
        user_id: 玩家 QQ 号。
        nickname: 玩家昵称（空串不更新）。
        opponent_rating: 对手（Bot 档位）固定分数。
        score: 得分，胜 1.0 / 和 0.5 / 负 0.0。
    """
    conn = _connect()
    try:
        row = conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM players WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        record = _row_to_record(row) if row else ensure_record(user_id, nickname)
        old_rating = record.rating
        new_rating_value = new_rating(old_rating, opponent_rating, score, record.games)
        won = score >= 1.0
        draw = 0.5 - 1e-9 < score < 0.5 + 1e-9
        record.rating = new_rating_value
        record.games += 1
        record.wins += int(won)
        record.draws += int(draw)
        record.losses += int(not won and not draw)
        record.max_challenged = max(record.max_challenged, opponent_rating)
        if won:
            record.max_beaten = max(record.max_beaten, opponent_rating)
        if nickname:
            record.nickname = nickname
        record.updated_at = time.time()
        conn.execute(
            f"INSERT OR REPLACE INTO players VALUES ({', '.join('?' * len(_COLUMNS))})",
            tuple(getattr(record, col) for col in _COLUMNS),
        )
        conn.commit()
    finally:
        conn.close()
    return new_rating_value - old_rating, new_rating_value


def get_rank(user_id: str) -> int | None:
    """返回玩家名次（1 起）；未入库返回 None。"""
    record = get_record(user_id)
    if record is None:
        return None
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM players WHERE rating > ?",
            (record.rating,),
        ).fetchone()
    finally:
        conn.close()
    return int(row[0]) + 1


def get_leaderboard(limit: int | None = None) -> list[tuple[int, PlayerRecord]]:
    """返回排行榜 [(名次, 记录), ...]，按分数降序、胜场降序。"""
    settings = get_settings()
    size = limit if limit is not None else settings.leaderboard_size
    conn = _connect()
    try:
        rows = conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM players "
            "ORDER BY rating DESC, wins DESC, updated_at ASC LIMIT ?",
            (size,),
        ).fetchall()
    finally:
        conn.close()
    return [(index, _row_to_record(row)) for index, row in enumerate(rows, start=1)]
