"""对局状态管理：内存 dict + JSON 落盘（data/chess_games.json）。

对局按用户隔离；长时间无操作的对局在下次访问时自动清除（避免内存泄漏）。
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import chess

from .config import get_settings

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(slots=True)
class GameConfig:
    """开局配置（供 GameManager.start 使用）。"""

    user_color: str  # "white" | "black"
    mode: str  # "practice" | "challenge"
    level_name: str  # 难度名或对手名
    skill: int
    movetime_ms: int
    depth: int
    opponent_rating: int = 0


@dataclass(slots=True)
class Game:
    """一局人机对局。"""

    user_id: str
    fen: str
    user_color: str  # "white" | "black"
    mode: str  # "practice" | "challenge"
    level_name: str  # 难度名或对手名
    skill: int
    movetime_ms: int
    depth: int
    opponent_rating: int = 0
    moves: list[str] = field(default_factory=list)  # UCI 走法序列（用于悔棋）
    started_at: float = field(default_factory=time.time)
    last_move_at: float = field(default_factory=time.time)

    def rebuild_board(self) -> chess.Board:
        """按走法序列重建棋盘（比直接 FEN 更可靠地支持悔棋）。"""
        board = chess.Board()
        for uci in self.moves:
            board.push_uci(uci)
        return board

    def last_pair(self) -> tuple[int, int] | None:
        """最近一步的 (from_square, to_square)，无走法返回 None。"""
        if not self.moves:
            return None
        move = chess.Move.from_uci(self.moves[-1])
        return move.from_square, move.to_square


class GameManager:
    """对局集合：get/start/remove/undo + JSON 持久化。"""

    def __init__(self) -> None:
        self._games: dict[str, Game] = {}
        self._load()

    # ── 持久化 ──

    def _path(self) -> Path:
        return _PROJECT_ROOT / "data" / "chess_games.json"

    def _load(self) -> None:
        path = self._path()
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        now = time.time()
        expire = get_settings().game_expire_seconds
        for item in raw:
            try:
                game = Game(**item)
            except TypeError:
                continue
            if now - game.last_move_at > expire:
                continue
            self._games[game.user_id] = game

    def _save(self) -> None:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(game) for game in self._games.values()]
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    # ── 对局操作 ──

    def get(self, user_id: str) -> tuple[Game | None, bool]:
        """返回 (对局, 是否因超时被清除)。"""
        game = self._games.get(user_id)
        if game is None:
            return None, False
        if time.time() - game.last_move_at > get_settings().game_expire_seconds:
            self.remove(user_id)
            return None, True
        return game, False

    def start(self, user_id: str, config: GameConfig) -> Game:
        """开始新对局（覆盖已有对局）。"""
        game = Game(
            user_id=user_id,
            fen=chess.Board().fen(),
            user_color=config.user_color,
            mode=config.mode,
            level_name=config.level_name,
            skill=config.skill,
            movetime_ms=config.movetime_ms,
            depth=config.depth,
            opponent_rating=config.opponent_rating,
        )
        self._games[user_id] = game
        self._save()
        return game

    def remove(self, user_id: str) -> Game | None:
        """移除对局并落盘，返回被移除的对局。"""
        game = self._games.pop(user_id, None)
        if game is not None:
            self._save()
        return game

    def touch(self, game: Game) -> None:
        """更新对局（走子/悔棋后调用并落盘）。"""
        game.last_move_at = time.time()
        self._save()
