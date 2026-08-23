"""棋盘渲染（三级降级）。

1. nonebot_plugin_htmlrender（Playwright 截图）渲染 HTML 棋盘为 PNG；
2. PIL 直接绘制棋盘图片（无浏览器依赖，兜底）；
3. 等宽文本棋盘（最后兜底）。
"""

from __future__ import annotations

import base64
import html
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import chess

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .game import Game

# 棋子 Unicode 字形（白=空心，黑=实心）
_GLYPHS: dict[str, str] = {
    "K": "♔",
    "Q": "♕",
    "R": "♖",
    "B": "♗",
    "N": "♘",
    "P": "♙",
    "k": "♚",
    "q": "♛",
    "r": "♜",
    "b": "♝",
    "n": "♞",
    "p": "♟",
}

_VIEWPORT_WIDTH = 540


@dataclass(frozen=True, slots=True)
class BoardHighlights:
    """棋盘高亮信息（合并渲染参数）。"""

    hints: frozenset[int] = field(default_factory=frozenset)
    last_move: tuple[int, int] | None = None
    check_square: int | None = None


def _square_class(
    file_index: int,
    rank: int,
    square: chess.Square,
    highlights: BoardHighlights,
) -> str:
    """计算格子的 CSS 类。"""
    classes = ["cell", "light" if (file_index + rank) % 2 == 0 else "dark"]
    if highlights.last_move is not None and square in highlights.last_move:
        classes.append("hl-last")
    elif highlights.check_square is not None and square == highlights.check_square:
        classes.append("hl-check")
    elif square in highlights.hints:
        classes.append("hint")
    return " ".join(classes)


def _coord_label(file_index: int, rank: int) -> str:
    """边缘格子显示坐标小字（a~h 在底线/顶线，1~8 在左右边）。"""
    parts: list[str] = []
    if rank in (1, 8):
        parts.append(chess.FILE_NAMES[file_index])
    if file_index in (0, 7):
        parts.append(str(rank))
    return "".join(parts)


def build_board_html(
    board: chess.Board,
    *,
    flip: bool = False,
    title: str = "",
    caption: str = "",
    highlights: BoardHighlights | None = None,
) -> str:
    """构建棋盘 HTML。flip=True 时黑方视角（rank 1 在顶部）。"""
    highlights = highlights or BoardHighlights()
    ranks = range(8, 0, -1) if not flip else range(1, 9)
    cells: list[str] = []
    for rank in ranks:
        for file_index in range(8):
            square = chess.square(file_index, rank - 1)
            piece = board.piece_at(square)
            glyph = _GLYPHS.get(piece.symbol(), "") if piece else ""
            label = _coord_label(file_index, rank)
            cls = _square_class(file_index, rank, square, highlights)
            label_html = f'<span class="coord">{label}</span>' if label else ""
            cells.append(f'<div class="{cls}">{label_html}{html.escape(glyph)}</div>')
    title_html = f'<div class="title">{html.escape(title)}</div>' if title else ""
    caption_html = (
        f'<div class="caption">{html.escape(caption)}</div>' if caption else ""
    )
    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<style>
  body {{ margin: 0; background: #f2efe9;
          font-family: "Segoe UI Symbol", "Segoe UI", sans-serif; }}
  .card {{ padding: 14px 0 18px; }}
  .title {{ font-family: "Microsoft YaHei", sans-serif; font-size: 17px;
            font-weight: 700; color: #333; text-align: center;
            margin-bottom: 10px; }}
  .board {{ width: 448px; height: 448px; display: grid;
            grid-template-columns: repeat(8, 56px);
            grid-template-rows: repeat(8, 56px);
            border: 2px solid #4a3f2f; margin: 0 auto; }}
  .cell {{ width: 56px; height: 56px; display: flex;
           align-items: center; justify-content: center;
           position: relative; font-size: 42px; line-height: 1;
           user-select: none; text-shadow: 0 0 3px rgba(255,255,255,.55); }}
  .light {{ background: #f0d9b5; }}
  .dark {{ background: #b58863; }}
  .hl-last {{ background: #e3c94a !important; }}
  .hl-check {{ background: #e05252 !important; }}
  .hint::after {{ content: ""; position: absolute; width: 16px;
                  height: 16px; border-radius: 50%;
                  background: rgba(0, 0, 0, .28); }}
  .coord {{ position: absolute; top: 1px; left: 3px; font-size: 10px;
            color: rgba(0, 0, 0, .5);
            font-family: "Microsoft YaHei", sans-serif; }}
  .caption {{ font-family: "Microsoft YaHei", sans-serif; font-size: 13px;
              color: #444; margin: 10px auto 0; text-align: center;
              line-height: 1.7; white-space: pre-wrap; max-width: 500px; }}
</style>
</head>
<body>
<div class="card">
{title_html}
<div class="board">
{"".join(cells)}
</div>
{caption_html}
</div>
</body>
</html>"""


async def _html_to_base64(board_html: str) -> str:
    """HTML → base64:// 图片字符串；失败返回空串。"""
    try:
        from nonebot_plugin_htmlrender import html_to_pic
    except ImportError:
        return ""
    try:
        pic = await html_to_pic(
            html=board_html,
            viewport={"width": _VIEWPORT_WIDTH, "height": 100},
            type="png",
            device_scale_factor=2,
        )
    except Exception:  # noqa: BLE001
        return ""
    return "base64://" + base64.b64encode(pic).decode("ascii")


def _check_square(board: chess.Board) -> int | None:
    if not board.is_check():
        return None
    for square in board.pieces(board.king, board.turn):
        return square
    return None


# ── PIL 图片兜底渲染 ──

_SQUARE = 56
_BOARD_PX = _SQUARE * 8
_MARGIN = 10
_LIGHT = (240, 217, 181)
_DARK = (181, 136, 99)
_LAST = (227, 201, 74)
_CHECK = (224, 82, 82)
_PIECE = (30, 30, 30)
_HINT = (120, 120, 120)
_BG = (242, 239, 233)
_TITLE_COLOR = (51, 51, 51)
_CAPTION_COLOR = (70, 70, 70)
_COORD_COLOR = (130, 115, 95)

_FONT_PIECE = Path(r"C:\Windows\Fonts\seguisym.ttf")
_FONT_CJK = Path(r"C:\Windows\Fonts\msyh.ttc")

_LINE_WRAP = 26  # 说明文字每行最大字符数


def _wrap_lines(text: str) -> list[str]:
    """按换行与最大宽度拆分说明文字。"""
    lines: list[str] = []
    for raw_line in text.split("\n"):
        segment = raw_line
        while len(segment) > _LINE_WRAP:
            lines.append(segment[:_LINE_WRAP])
            segment = segment[_LINE_WRAP:]
        lines.append(segment)
    return lines


def _pil_fonts() -> tuple | None:
    """加载棋子字形与中文等字体；失败返回 None。"""
    try:
        from PIL import ImageFont

        piece = ImageFont.truetype(str(_FONT_PIECE), 46)
        cjk = ImageFont.truetype(str(_FONT_CJK), 16)
        title_font = ImageFont.truetype(str(_FONT_CJK), 20)
    except OSError:
        return None
    return piece, cjk, title_font


@dataclass(slots=True)
class _PilContext:
    """PIL 绘制上下文。"""

    draw: object
    piece_font: object
    cjk_font: object
    highlights: BoardHighlights


def _draw_square(
    ctx: _PilContext,
    board: chess.Board,
    square: chess.Square,
    x: int,
    y: int,
) -> None:
    """绘制单个棋盘格（底色/坐标/棋子/提示点）。"""
    file_index = chess.square_file(square)
    rank = chess.square_rank(square) + 1
    highlights = ctx.highlights
    color = _LIGHT if (file_index + rank) % 2 == 0 else _DARK
    if highlights.last_move is not None and square in highlights.last_move:
        color = _LAST
    elif highlights.check_square is not None and square == highlights.check_square:
        color = _CHECK
    ctx.draw.rectangle((x, y, x + _SQUARE - 1, y + _SQUARE - 1), fill=color)

    label = _coord_label(file_index, rank)
    if label:
        ctx.draw.text(
            (x + 2, y + 1), label, font=ctx.cjk_font, fill=_COORD_COLOR, anchor="la"
        )

    piece = board.piece_at(square)
    if piece:
        glyph = _GLYPHS.get(piece.symbol(), "")
        if glyph:
            ctx.draw.text(
                (x + _SQUARE // 2, y + _SQUARE // 2),
                glyph,
                font=ctx.piece_font,
                fill=_PIECE,
                anchor="mm",
            )

    if square in highlights.hints:
        center_x = x + _SQUARE // 2
        center_y = y + _SQUARE // 2
        radius = 8
        ctx.draw.ellipse(
            (
                center_x - radius,
                center_y - radius,
                center_x + radius,
                center_y + radius,
            ),
            fill=_HINT,
        )


def _pil_render_image(
    board: chess.Board,
    *,
    flip: bool,
    title: str,
    caption: str,
    highlights: BoardHighlights,
) -> str:
    """用 PIL 绘制棋盘为 base64:// 图片；失败返回空串。"""
    try:
        from PIL import Image, ImageDraw

        fonts = _pil_fonts()
        if fonts is None:
            return ""
        piece_font, cjk_font, title_font = fonts
    except ImportError:
        return ""

    caption_lines = _wrap_lines(caption) if caption else []
    width = _BOARD_PX + _MARGIN * 2
    title_h = 34 if title else 0
    caption_h = len(caption_lines) * 24
    height = _MARGIN + title_h + 6 + _BOARD_PX + 8 + caption_h + _MARGIN

    image = Image.new("RGB", (width, height), _BG)
    draw = ImageDraw.Draw(image)

    if title:
        draw.text(
            (width // 2, _MARGIN),
            title,
            font=title_font,
            fill=_TITLE_COLOR,
            anchor="ma",
        )

    origin_x = _MARGIN
    origin_y = _MARGIN + title_h + 6
    ctx = _PilContext(
        draw=draw,
        piece_font=piece_font,
        cjk_font=cjk_font,
        highlights=highlights,
    )
    ranks = range(8, 0, -1) if not flip else range(1, 9)
    for row, rank in enumerate(ranks):
        for file_index in range(8):
            square = chess.square(file_index, rank - 1)
            _draw_square(
                ctx,
                board,
                square,
                origin_x + file_index * _SQUARE,
                origin_y + row * _SQUARE,
            )

    for index, line in enumerate(caption_lines):
        draw.text(
            (width // 2, origin_y + _BOARD_PX + 8 + index * 24),
            line,
            font=cjk_font,
            fill=_CAPTION_COLOR,
            anchor="ma",
        )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "base64://" + base64.b64encode(buffer.getvalue()).decode("ascii")


async def render_game_image(
    game: Game,
    *,
    title: str = "",
    caption: str = "",
    hints: set[int] | None = None,
) -> str:
    """渲染对局棋盘为图片字符串（htmlrender → PIL → 空串）。"""
    board = game.rebuild_board()
    highlights = BoardHighlights(
        hints=frozenset(hints or set()),
        last_move=game.last_pair(),
        check_square=_check_square(board),
    )
    board_html = build_board_html(
        board,
        flip=game.user_color == "black",
        title=title,
        caption=caption,
        highlights=highlights,
    )
    image = await _html_to_base64(board_html)
    if image:
        return image
    return _pil_render_image(
        board,
        flip=game.user_color == "black",
        title=title,
        caption=caption,
        highlights=highlights,
    )


async def render_diagram(
    fen: str,
    *,
    title: str = "",
    caption: str = "",
    highlights: set[int] | None = None,
    flip: bool = False,
) -> str:
    """渲染自定义局面（教程用）为图片字符串（htmlrender → PIL → 空串）。"""
    board = chess.Board(fen)
    highlights_obj = BoardHighlights(hints=frozenset(highlights or set()))
    board_html = build_board_html(
        board,
        flip=flip,
        title=title,
        caption=caption,
        highlights=highlights_obj,
    )
    image = await _html_to_base64(board_html)
    if image:
        return image
    return _pil_render_image(
        board,
        flip=flip,
        title=title,
        caption=caption,
        highlights=highlights_obj,
    )


def render_text_board(game: Game, caption: str = "") -> str:
    """等宽文本棋盘（图片渲染不可用时的兜底）。"""
    board = game.rebuild_board()
    ranks = range(8, 0, -1) if game.user_color == "white" else range(1, 9)
    lines = ["  a b c d e f g h"]
    for rank in ranks:
        row = []
        for file_index in range(8):
            piece = board.piece_at(chess.square(file_index, rank - 1))
            row.append(piece.symbol() if piece else ".")
        lines.append(f"{rank} {' '.join(row)} {rank}")
    lines.append("  a b c d e f g h")
    if caption:
        lines.append(caption)
    return "\n".join(lines)


def render_text_fen(fen: str) -> str:
    """任意 FEN 的文本棋盘（教程兜底）。"""
    board = chess.Board(fen)
    lines = ["  a b c d e f g h"]
    for rank in range(8, 0, -1):
        row = []
        for file_index in range(8):
            piece = board.piece_at(chess.square(file_index, rank - 1))
            row.append(piece.symbol() if piece else ".")
        lines.append(f"{rank} {' '.join(row)} {rank}")
    lines.append("  a b c d e f g h")
    return "\n".join(lines)


def flatten_hints(squares: Iterable[int]) -> set[int]:
    """把任意可迭代的格子转为 set。"""
    return set(squares)
