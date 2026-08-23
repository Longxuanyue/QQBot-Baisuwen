"""新手教程：一组程序化生成的棋盘讲解图。

每张卡片 = 布置好的局面 + 合法走法高亮 + 标题/说明文字，全部由
渲染模板生成，无需任何美术素材。图片渲染失败时返回空串，由调用方
降级为文字说明。
"""

from __future__ import annotations

import chess

from .render import render_diagram

_START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
_FEN_ROOK = "8/8/8/8/4R3/8/8/8 w - - 0 1"
_FEN_BISHOP = "8/8/8/8/2B5/8/8/8 w - - 0 1"
_FEN_KNIGHT = "8/8/8/8/3N4/8/8/8 w - - 0 1"
_FEN_QUEEN = "8/8/8/8/3Q4/8/8/8 w - - 0 1"
_FEN_CASTLE = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
_FEN_EN_PASSANT = "8/8/8/3pP3/8/8/8/8 w - d6 0 2"
_FEN_PROMOTE = "8/4P3/8/8/8/8/8/8 w - - 0 1"
_FEN_CHECK = "4k3/8/8/8/8/8/8/4R3 w - - 0 1"


def _moves_to(
    fen: str, from_square: chess.Square, *, capture_only: bool = False
) -> set[int]:
    """某格棋子的合法目标格（可选只取吃子走法）。"""
    board = chess.Board(fen)
    squares: set[int] = set()
    for move in board.legal_moves:
        if move.from_square != from_square:
            continue
        if capture_only and not board.is_capture(move):
            continue
        squares.add(move.to_square)
    return squares


def _attacks(fen: str, square: chess.Square) -> set[int]:
    """某格棋子可攻击/走到的格子（滑子与跳跃子）。"""
    board = chess.Board(fen)
    return set(board.attacks(square))


def _cards() -> list[dict]:
    """教程卡片定义（顺序即发送顺序）。"""
    return [
        {
            "fen": _START_FEN,
            "title": "① 棋盘与坐标",
            "caption": (
                "白方在下（第 1~2 横线），黑方在上（第 7~8 横线）。\n"
                "竖线 a~h，横线 1~8，例如 e4 就是 e 列第 4 格。\n"
                "回合 = 你走一步 + 机器人走一步。"
            ),
        },
        {
            "fen": _START_FEN,
            "title": "② 兵的走法",
            "caption": (
                "兵只能向前走一格（初始位置可走两格），\n"
                "只能斜着吃子（绿色圆点为 e2 兵可走的格子）。\n"
                "兵到达对方底线时必须升变为后/车/象/马。"
            ),
            "highlights": _moves_to(_START_FEN, chess.E2),
        },
        {
            "fen": _FEN_ROOK,
            "title": "③ 车的走法",
            "caption": "车沿横线或竖线走任意格，不能越子，可吃路径上的第一个子。",
            "highlights": _attacks(_FEN_ROOK, chess.E4),
        },
        {
            "fen": _FEN_BISHOP,
            "title": "④ 象的走法",
            "caption": "象沿斜线走任意格，始终停留在同色格上。",
            "highlights": _attacks(_FEN_BISHOP, chess.C4),
        },
        {
            "fen": _FEN_KNIGHT,
            "title": "⑤ 马的走法",
            "caption": "马走 L 形（2+1），可以越过其他棋子，是唯一会跳的棋子。",
            "highlights": _attacks(_FEN_KNIGHT, chess.D4),
        },
        {
            "fen": _FEN_QUEEN,
            "title": "⑥ 后的走法",
            "caption": "后 = 车 + 象，横竖斜都能走，是威力最大的棋子。",
            "highlights": _attacks(_FEN_QUEEN, chess.D4),
        },
        {
            "fen": _FEN_CASTLE,
            "title": "⑦ 王与易位",
            "caption": (
                "王横竖斜走一格。特殊走法「王车易位」：\n"
                "王向车走两格，车跳到王的另一侧（绿色为白王可易位目标格）。\n"
                "要求：王与车都未动过、中间无子、王不在将军且不经过受攻击格。"
            ),
            "highlights": {chess.G1, chess.C1},
        },
        {
            "fen": _FEN_EN_PASSANT,
            "title": "⑧ 吃过路兵",
            "caption": (
                "黑兵刚从 d7 走到 d5（一步两格），\n"
                "白兵 e5 可以「斜吃」到黑兵身后的 d6 格（绿色）。\n"
                "此走法必须在对方刚走两格兵的下一回合立即执行。"
            ),
            "highlights": _moves_to(_FEN_EN_PASSANT, chess.E5, capture_only=True),
        },
        {
            "fen": _FEN_PROMOTE,
            "title": "⑨ 升变",
            "caption": (
                "兵到达对方底线必须升变（绿色为 e7 兵的目标格）。\n"
                "一般升为后，输入走法时可用 e8=Q 指定，默认自动变后。"
            ),
            "highlights": _moves_to(_FEN_PROMOTE, chess.E7),
        },
        {
            "fen": _FEN_CHECK,
            "title": "⑩ 将军与胜负",
            "caption": (
                "红格 = 黑王正被将军，必须立即化解。\n"
                "将死 = 无法化解，对方获胜；无子可走却未被将军 = 逼和；\n"
                "50 回合无吃子/无兵动、三次重复、子力不足 = 自动和棋。"
            ),
        },
    ]


TUTORIAL_TEXT = """📖 国际象棋规则速查（图片渲染不可用时的文字版）：
· 走法：直接发送目标格，如 e4、Nf3、O-O（王车易位）、e8=Q（升变）或 e2e4
· 吃子：自动判断；兵斜吃，例如 exd5
· 将军：你的王被攻击时必须化解；无解则输
· 和棋：无子可走、三次重复、50 回合无吃子、子力不足
· 常用指令：/国际象棋 开局 · /棋局 看盘 · /悔棋 · /认输 · /退出棋局"""


async def build_tutorial_cards() -> list[tuple[str, str]]:
    """生成教程图片列表 [(标题, base64 图片串), ...]，失败的卡片被跳过。"""
    images: list[tuple[str, str]] = []
    for card in _cards():
        image = await render_diagram(
            card["fen"],
            title=card["title"],
            caption=card.get("caption", ""),
            highlights=card.get("highlights"),
        )
        if image:
            images.append((card["title"], image))
    return images
