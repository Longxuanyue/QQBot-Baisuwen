"""Bot 走法引擎。

优先使用 Stockfish（UCI 协议，单进程共享 + asyncio 锁串行化）；未配置
或启动失败时降级为内置纯 Python minimax（子力分 + 位置分表 + alpha-beta
剪枝）。
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from pathlib import Path

import chess

from .config import get_settings

# 子力基础分（兵 = 100）
_PIECE_VALUES: dict[int, int] = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20000,
}

# 位置分表（白方视角，索引 = 格序号，0 为 a1）；黑方镜像使用
_PST_PAWN = [
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    50,
    50,
    50,
    50,
    50,
    50,
    50,
    50,
    10,
    10,
    20,
    30,
    30,
    20,
    10,
    10,
    5,
    5,
    10,
    25,
    25,
    10,
    5,
    5,
    0,
    0,
    0,
    20,
    20,
    0,
    0,
    0,
    5,
    -5,
    -10,
    0,
    0,
    -10,
    -5,
    5,
    5,
    10,
    10,
    -20,
    -20,
    10,
    10,
    5,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
]
_PST_KNIGHT = [
    -50,
    -40,
    -30,
    -30,
    -30,
    -30,
    -40,
    -50,
    -40,
    -20,
    0,
    0,
    0,
    0,
    -20,
    -40,
    -30,
    0,
    10,
    15,
    15,
    10,
    0,
    -30,
    -30,
    5,
    15,
    20,
    20,
    15,
    5,
    -30,
    -30,
    0,
    15,
    20,
    20,
    15,
    0,
    -30,
    -30,
    5,
    10,
    15,
    15,
    10,
    5,
    -30,
    -40,
    -20,
    0,
    5,
    5,
    0,
    -20,
    -40,
    -50,
    -40,
    -30,
    -30,
    -30,
    -30,
    -40,
    -50,
]
_PST_BISHOP = [
    -20,
    -10,
    -10,
    -10,
    -10,
    -10,
    -10,
    -20,
    -10,
    0,
    0,
    0,
    0,
    0,
    0,
    -10,
    -10,
    0,
    5,
    10,
    10,
    5,
    0,
    -10,
    -10,
    5,
    5,
    10,
    10,
    5,
    5,
    -10,
    -10,
    0,
    10,
    10,
    10,
    10,
    0,
    -10,
    -10,
    10,
    10,
    10,
    10,
    10,
    10,
    -10,
    -10,
    5,
    0,
    0,
    0,
    0,
    5,
    -10,
    -20,
    -10,
    -10,
    -10,
    -10,
    -10,
    -10,
    -20,
]
_PST_ROOK = [
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    5,
    10,
    10,
    10,
    10,
    10,
    10,
    5,
    -5,
    0,
    0,
    0,
    0,
    0,
    0,
    -5,
    -5,
    0,
    0,
    0,
    0,
    0,
    0,
    -5,
    -5,
    0,
    0,
    0,
    0,
    0,
    0,
    -5,
    -5,
    0,
    0,
    0,
    0,
    0,
    0,
    -5,
    -5,
    0,
    0,
    0,
    0,
    0,
    0,
    -5,
    0,
    0,
    0,
    5,
    5,
    0,
    0,
    0,
]
_PST_QUEEN = [
    -20,
    -10,
    -10,
    -5,
    -5,
    -10,
    -10,
    -20,
    -10,
    0,
    0,
    0,
    0,
    0,
    0,
    -10,
    -10,
    0,
    5,
    5,
    5,
    5,
    0,
    -10,
    -5,
    0,
    5,
    5,
    5,
    5,
    0,
    -5,
    0,
    0,
    5,
    5,
    5,
    5,
    0,
    -5,
    -10,
    5,
    5,
    5,
    5,
    5,
    0,
    -10,
    -10,
    0,
    5,
    0,
    0,
    0,
    0,
    -10,
    -20,
    -10,
    -10,
    -5,
    -5,
    -10,
    -10,
    -20,
]
_PST_KING = [
    -30,
    -40,
    -40,
    -50,
    -50,
    -40,
    -40,
    -30,
    -30,
    -40,
    -40,
    -50,
    -50,
    -40,
    -40,
    -30,
    -30,
    -40,
    -40,
    -50,
    -50,
    -40,
    -40,
    -30,
    -30,
    -40,
    -40,
    -50,
    -50,
    -40,
    -40,
    -30,
    -20,
    -30,
    -30,
    -40,
    -40,
    -30,
    -30,
    -20,
    -10,
    -20,
    -20,
    -20,
    -20,
    -20,
    -20,
    -10,
    20,
    20,
    0,
    0,
    0,
    0,
    20,
    20,
    20,
    30,
    10,
    0,
    0,
    10,
    30,
    20,
]

_PST: dict[int, list[int]] = {
    chess.PAWN: _PST_PAWN,
    chess.KNIGHT: _PST_KNIGHT,
    chess.BISHOP: _PST_BISHOP,
    chess.ROOK: _PST_ROOK,
    chess.QUEEN: _PST_QUEEN,
    chess.KING: _PST_KING,
}


def _pst_index(square: chess.Square, color: chess.Color) -> int:
    file_index = chess.square_file(square)
    rank_index = chess.square_rank(square)
    if color == chess.WHITE:
        return rank_index * 8 + file_index
    return (7 - rank_index) * 8 + file_index


def _evaluate(board: chess.Board) -> int:
    """白方视角的静态评估：子力 + 位置分。"""
    score = 0
    for square, piece in board.piece_map().items():
        table = _PST[piece.piece_type]
        value = _PIECE_VALUES[piece.piece_type] + table[_pst_index(square, piece.color)]
        score += value if piece.color == chess.WHITE else -value
    return score


def _ordered_moves(board: chess.Board) -> list[chess.Move]:
    """走法排序：吃子/升变优先，提升剪枝效率。"""
    moves = list(board.legal_moves)

    def sort_key(move: chess.Move) -> tuple[int]:
        bonus = 0
        if board.is_capture(move):
            captured = board.piece_at(move.to_square)
            moving = board.piece_at(move.from_square)
            if captured is not None and moving is not None:
                bonus = (
                    10 * _PIECE_VALUES[captured.piece_type]
                    - _PIECE_VALUES[moving.piece_type]
                )
        if move.promotion is not None:
            bonus += _PIECE_VALUES[move.promotion]
        return (-bonus,)

    return sorted(moves, key=sort_key)


def _negamax(board: chess.Board, depth: int, alpha: int, beta: int) -> int:
    if depth == 0 or board.is_game_over():
        value = _evaluate(board)
        return value if board.turn == chess.WHITE else -value
    best = -10_000_000
    for move in _ordered_moves(board):
        board.push(move)
        value = -_negamax(board, depth - 1, -beta, -alpha)
        board.pop()
        best = max(best, value)
        alpha = max(alpha, best)
        if alpha >= beta:
            break
    return best


def minimax_move(board: chess.Board, depth: int) -> chess.Move:
    """纯 Python minimax 根节点选择（同分随机，避免重复开局）。"""
    moves = _ordered_moves(board)
    best_value = -10_000_000
    best_moves: list[chess.Move] = []
    for move in moves:
        board.push(move)
        value = -_negamax(board, depth - 1, -10_000_000, 10_000_000)
        board.pop()
        if value > best_value:
            best_value = value
            best_moves = [move]
        elif value == best_value:
            best_moves.append(move)
    return random.choice(best_moves)


def _resolve_engine_path(configured: str) -> Path | None:
    """解析 Stockfish 路径（相对路径按项目根目录）；不存在返回 None。"""
    path = Path(configured)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[3] / path
    return path if path.is_file() else None


class ChessEngine:
    """共享引擎单例：一个 Stockfish 进程，所有调用经 asyncio 锁串行。"""

    _process: object | None = None  # chess.engine.SimpleEngine
    _lock = asyncio.Lock()
    _init_attempted = False

    @classmethod
    async def _ensure(cls) -> None:
        if cls._init_attempted:
            return
        cls._init_attempted = True
        configured = get_settings().stockfish_path
        if not configured:
            return
        path = _resolve_engine_path(configured)
        if path is None:
            return
        try:
            import chess.engine

            process = await asyncio.to_thread(
                chess.engine.SimpleEngine.popen_uci, str(path)
            )
            await asyncio.to_thread(process.configure, {"Threads": 1, "Hash": 32})
            cls._process = process
        except Exception:  # noqa: BLE001
            cls._process = None

    @classmethod
    async def choose_move(
        cls, board: chess.Board, skill: int, movetime_ms: int, depth: int
    ) -> chess.Move:
        """为当前局面选择 Bot 走法。

        Args:
            board: 当前棋盘。
            skill: Stockfish Skill Level（0~20）。
            movetime_ms: Stockfish 每步思考毫秒数。
            depth: 纯 Python 引擎的搜索深度。
        """
        await cls._ensure()
        if cls._process is not None:
            try:
                import chess.engine

                async with cls._lock:

                    def _play() -> chess.Move:
                        process = cls._process
                        assert process is not None
                        process.configure({"Skill Level": skill})
                        limit = chess.engine.Limit(movetime=movetime_ms)
                        result = process.play(board, limit)
                        return result.move

                    return await asyncio.to_thread(_play)
            except Exception:  # noqa: BLE001
                pass
        return await asyncio.to_thread(minimax_move, board, depth)

    @classmethod
    async def shutdown(cls) -> None:
        """退出 Stockfish 进程（NoneBot 停机时调用）。"""
        if cls._process is None:
            return
        process = cls._process
        cls._process = None
        with contextlib.suppress(Exception):
            await asyncio.to_thread(process.quit)
