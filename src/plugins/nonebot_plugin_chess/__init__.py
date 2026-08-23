"""nonebot_plugin_chess - 私聊国际象棋人机对弈插件。

- 练习局（简单/普通/困难）：不计分，支持悔棋
- 挑战局（青铜~终极六档对手）：Elo 段位分计分，排行榜按分数排名
- 新手图文教程：/国际象棋 教程
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import chess
from nonebot import get_driver, on_command, on_message
from nonebot.adapters.onebot.v11 import (
    Bot,
    Message,
    MessageEvent,
    MessageSegment,
    PrivateMessageEvent,
)
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

if TYPE_CHECKING:
    from nonebot.matcher import Matcher

from .config import get_settings
from .engine import ChessEngine
from .game import Game, GameConfig, GameManager
from .rating import get_leaderboard, get_rank, get_record, record_result
from .render import render_game_image, render_text_board
from .tutorial import TUTORIAL_TEXT, build_tutorial_cards

__version__ = "0.1.0"

__plugin_meta__ = PluginMetadata(
    name="国际象棋",
    description="私聊人机国际象棋对弈：练习局（简单/普通/困难）与计分挑战局，支持排行榜",
    usage=(
        "/国际象棋 开始练习局；/国际象棋 教程 新手教程\n"
        "/国际象棋 <白|黑> <简单|普通|困难> 自定义练习局\n"
        "/挑战 <对手> 计分挑战局（青铜/白银/黄金/钻石/王者/终极）\n"
        "对局中直接发送走法（如 e4、Nf3、e2e4、O-O）\n"
        "/棋局 查看棋盘 · /悔棋 撤一步（仅练习局）· /认输 · /退出棋局\n"
        "/排行榜 查看分数榜 · /我的分数 查看个人分数"
    ),
    type="application",
    homepage="https://github.com/baisuwen",
    supported_adapters={"~onebot.v11"},
    extra={
        "author": "baisuwen",
        "version": __version__,
        "commands": [
            {
                "name": "/国际象棋",
                "description": "开始/查看练习局（可用 白|黑 与 简单|普通|困难 参数）",
            },
            {"name": "/国际象棋 教程", "description": "新手图文教程"},
            {
                "name": "/挑战 <对手>",
                "description": "计分挑战局：青铜/白银/黄金/钻石/王者/终极",
            },
            {"name": "/棋局", "description": "查看当前棋盘"},
            {"name": "/悔棋", "description": "撤销一步（仅练习局）"},
            {"name": "/认输 /投降", "description": "认输结束对局"},
            {"name": "/退出棋局", "description": "放弃当前对局（挑战局按认输计分）"},
            {"name": "/排行榜", "description": "查看段位分排行榜"},
            {"name": "/我的分数", "description": "查看个人分数、战绩与最高挑战"},
        ],
    },
)

# ── 常量 ──

COLOR_ALIASES: dict[str, str] = {
    "白": "white",
    "white": "white",
    "黑": "black",
    "black": "black",
}

#: 练习局难度表（skill = Stockfish 等级，depth = 纯 Python 引擎深度）
PRACTICE_LEVELS: dict[str, dict[str, int]] = {
    "简单": {"skill": 2, "movetime": 200, "depth": 1},
    "普通": {"skill": 9, "movetime": 500, "depth": 2},
    "困难": {"skill": 16, "movetime": 1000, "depth": 3},
}

#: 挑战局对手表（rating = 对手固定分，用于 Elo 结算）
OPPONENTS: dict[str, dict[str, int]] = {
    "青铜": {"rating": 1000, "skill": 2, "movetime": 200, "depth": 1},
    "白银": {"rating": 1300, "skill": 9, "movetime": 500, "depth": 2},
    "黄金": {"rating": 1600, "skill": 13, "movetime": 800, "depth": 2},
    "钻石": {"rating": 1900, "skill": 16, "movetime": 1000, "depth": 3},
    "王者": {"rating": 2200, "skill": 20, "movetime": 2000, "depth": 3},
    "终极": {"rating": 2500, "skill": 20, "movetime": 3000, "depth": 3},
}

_UCI_WITH_PROMO_LEN = 4  # 如 e7e8，可补 q 作为默认升变
_MASK_KEEP = 4  # 昵称兜底时保留的 QQ 号前缀位数
_UNDO_PLIES = 2  # 悔棋撤销的步数（用户 + Bot 各一步）

_HELP_TEXT = (
    "♟️ 国际象棋 · 私聊人机对弈\n"
    "· /国际象棋 开始练习局（默认执白·普通）\n"
    "· /国际象棋 <白|黑> <简单|普通|困难> 自定义练习局\n"
    "· /国际象棋 教程 新手图文教程\n"
    "· /挑战 <对手> 计分挑战局（发送 /挑战 查看对手列表）\n"
    "· /棋局 查看棋盘 · /悔棋（仅练习局）· /认输 · /退出棋局\n"
    "· /排行榜 段位分榜 · /我的分数 个人分数\n"
    "对局中直接发送走法即可：e4 / Nf3 / e2e4 / O-O / e8=Q"
)

_OPPONENT_LIST_TEXT = (
    "可选挑战对手（固定分，用于计分）：\n"
    + "\n".join(f"· {name}（{info['rating']} 分）" for name, info in OPPONENTS.items())
    + "\n用法：/挑战 <对手名>（如 /挑战 黄金）"
)

_PRIVATE_ONLY = "♟️ 国际象棋仅支持私聊使用，请添加机器人好友后私聊~"

games = GameManager()


@get_driver().on_shutdown
async def _on_shutdown() -> None:
    """停机时退出 Stockfish 进程。"""
    await ChessEngine.shutdown()


# ── 工具函数 ──


def _user_label(game: Game) -> str:
    return "白" if game.user_color == "white" else "黑"


def _game_status(game: Game) -> str:
    board = game.rebuild_board()
    return (
        f"你执{_user_label(game)} · 第 {board.fullmove_number} 回合 · 轮到你了\n"
        f"发送走法（如 e4 / Nf3 / e2e4 / O-O），或 /悔棋 /认输 /退出棋局"
    )


def _mask_qq(user_id: str) -> str:
    if len(user_id) > _MASK_KEEP:
        return f"{user_id[:_MASK_KEEP]}****"
    return user_id


def _opponent_name(rating: int) -> str:
    for name, info in OPPONENTS.items():
        if info["rating"] == rating:
            return name
    return ""


def _try_parse_move(board: chess.Board, candidate: str) -> chess.Move | None:
    """尝试把候选文本解析为合法走法。"""
    try:
        move = board.parse_san(candidate)
        if move in board.legal_moves:
            return move
    except ValueError:
        return None
    return None


def _parse_move(board: chess.Board, text: str) -> chess.Move | None:
    """解析走法：SAN（e4/Nf3/O-O）或 UCI（e2e4 / e7e8q）。"""
    raw = text.strip().replace(" ", "")
    if not raw:
        return None
    san_text = raw.lower().replace("o-o-o", "O-O-O").replace("o-o", "O-O")
    uci_text = raw.lower()
    candidates = [san_text, uci_text]
    if len(uci_text) == _UCI_WITH_PROMO_LEN:
        candidates.append(uci_text + "q")  # 升变默认变后
    for candidate in candidates:
        move = _try_parse_move(board, candidate)
        if move is not None:
            return move
    return None


async def _fetch_nickname(bot: Bot, user_id: str) -> str:
    try:
        info = await bot.get_stranger_info(user_id=int(user_id), no_cache=False)
        return str(info.get("nickname", ""))
    except Exception:  # noqa: BLE001
        return ""


async def _send_board(
    bot: Bot, event: MessageEvent, game: Game, caption: str = ""
) -> None:
    """发送棋盘（优先图片，失败降级文本）。"""
    title = f"{'练习局' if game.mode == 'practice' else '挑战局'} · {game.level_name}"
    text = caption or _game_status(game)
    image = await render_game_image(game, title=title, caption=text)
    if image:
        await bot.send(event, MessageSegment.image(image))
    else:
        await bot.send(event, f"{title}\n{text}\n{render_text_board(game)}")


async def _send_tutorial(bot: Bot, event: MessageEvent) -> None:
    cards = await build_tutorial_cards()
    if not cards:
        await chess_cmd.finish(TUTORIAL_TEXT)
    for _, image in cards:
        await bot.send(event, MessageSegment.image(image))
    await chess_cmd.finish(
        "💡 看完后发送 /国际象棋 即可开始练习局；对局中直接发走法（如 e4）"
    )


async def _apply_turn(bot: Bot, event: MessageEvent, game: Game, text: str) -> None:
    """执行用户走法 → Bot 应手 → 判定结束。"""
    board = game.rebuild_board()
    move = _parse_move(board, text)
    if move is None:
        await bot.send(
            event,
            "❌ 无法识别或不合法的走法：" + text + "\n"
            "例：e4 / Nf3 / e2e4 / O-O（王车易位）/ e8=Q（升变）；"
            "发送 /棋局 查看棋盘，/退出棋局 结束对局",
        )
        return

    board.push(move)
    game.moves.append(move.uci())
    games.touch(game)
    if board.is_game_over():
        await _finish_game(bot, event, game, board)
        return

    bot_move = await ChessEngine.choose_move(
        board, game.skill, game.movetime_ms, game.depth
    )
    board.push(bot_move)
    game.moves.append(bot_move.uci())
    games.touch(game)
    if board.is_game_over():
        await _finish_game(bot, event, game, board)
        return

    await _send_board(
        bot,
        event,
        game,
        f"你：{move.uci()} → 机器人：{bot_move.uci()}\n{_game_status(game)}",
    )


def _result_score(game: Game, board: chess.Board) -> tuple[str, float]:
    """返回 (结果说明, 玩家得分)。"""
    if board.is_checkmate():
        loser = board.turn  # 轮到走棋的一方被将死
        winner = chess.WHITE if loser == chess.BLACK else chess.BLACK
        user_white = game.user_color == "white"
        if (winner == chess.WHITE) == user_white:
            return "🎉 你将死了机器人，胜利！", 1.0
        return "😵 你被将死了，机器人获胜。", 0.0
    draw_cases = (
        (board.is_stalemate(), "🤝 逼和：你无子可走，和棋。"),
        (board.is_insufficient_material(), "🤝 和棋：双方子力不足。"),
        (board.is_fifty_moves(), "🤝 和棋：50 回合无吃子或无兵动。"),
        (board.is_repetition(3), "🤝 和棋：三次重复局面。"),
    )
    for is_draw, message in draw_cases:
        if is_draw:
            return message, 0.5
    return "对局结束。", 0.5


async def _finish_game(
    bot: Bot, event: MessageEvent, game: Game, board: chess.Board
) -> None:
    text, score = _result_score(game, board)
    games.remove(game.user_id)
    lines = [text]
    if game.mode == "challenge":
        nickname = await _fetch_nickname(bot, game.user_id)
        delta, new_rating = record_result(
            game.user_id, nickname, game.opponent_rating, score
        )
        lines.append(f"段位分 {delta:+d} → {new_rating}")
    await bot.send(event, "\n".join(lines))


async def _undo_flow(bot: Bot, event: MessageEvent, matcher: Matcher) -> None:
    game, _ = games.get(str(event.user_id))
    if game is None:
        await matcher.finish("当前没有进行中的对局~")
    if game.mode == "challenge":
        await matcher.finish("❌ 挑战局不支持悔棋。")
    if not game.moves:
        await matcher.finish("还没有可撤销的走法。")
    if len(game.moves) >= _UNDO_PLIES:
        del game.moves[-_UNDO_PLIES:]
    else:
        game.moves.clear()
    game.fen = game.rebuild_board().fen()
    games.touch(game)
    await _send_board(bot, event, game, "已撤销一步，轮到你了。")


async def _resign_flow(event: MessageEvent, matcher: Matcher) -> None:
    game, _ = games.get(str(event.user_id))
    if game is None:
        await matcher.finish("当前没有进行中的对局~")
    games.remove(game.user_id)
    if game.mode == "challenge":
        delta, new_rating = record_result(game.user_id, "", game.opponent_rating, 0.0)
        await matcher.finish(f"你认输了，对局结束。段位分 {delta:+d} → {new_rating}")
    await matcher.finish("你认输了，对局结束。下次再来~")


async def _quit_flow(event: MessageEvent, matcher: Matcher) -> None:
    game, _ = games.get(str(event.user_id))
    if game is None:
        await matcher.finish("当前没有进行中的对局~")
    games.remove(game.user_id)
    if game.mode == "challenge":
        delta, new_rating = record_result(game.user_id, "", game.opponent_rating, 0.0)
        await matcher.finish(
            f"已退出挑战局（按认输计分）。段位分 {delta:+d} → {new_rating}"
        )
    await matcher.finish("已退出对局，欢迎再来~")


# ── 命令注册 ──


chess_cmd = on_command("国际象棋", aliases={"chess"}, priority=5, block=True)


@chess_cmd.handle()
async def handle_chess(
    bot: Bot, event: MessageEvent, arg: Message = CommandArg()
) -> None:
    if not isinstance(event, PrivateMessageEvent):
        await chess_cmd.finish(_PRIVATE_ONLY)

    text = arg.extract_plain_text().strip()
    user_id = str(event.user_id)

    if text in ("教程", "help", "帮助", "规则"):
        await _send_tutorial(bot, event)
        return

    game, expired = games.get(user_id)
    if game is None:
        if expired:
            await chess_cmd.send("⚠️ 上一局因长时间未操作已自动结束。")
    else:
        if text and text not in COLOR_ALIASES and text not in PRACTICE_LEVELS:
            await _apply_turn(bot, event, game, text)  # 对局中直接给走法
            return
        await _send_board(
            bot,
            event,
            game,
            "已有一局进行中。直接发送走法（如 e4），或 /棋局 /悔棋 /认输 /退出棋局。",
        )
        return

    color = get_settings().default_color
    level_name = get_settings().default_difficulty
    for token in text.split():
        if token in COLOR_ALIASES:
            color = COLOR_ALIASES[token]
        elif token in PRACTICE_LEVELS:
            level_name = token
        else:
            await chess_cmd.finish(_HELP_TEXT)
    level = PRACTICE_LEVELS[level_name]
    config = GameConfig(
        user_color=color,
        mode="practice",
        level_name=level_name,
        skill=level["skill"],
        movetime_ms=level["movetime"],
        depth=level["depth"],
    )
    game = games.start(user_id, config)
    await _send_board(
        bot, event, game, f"♟️ 练习局开始！你执{_user_label(game)} · 难度 {level_name}。"
    )


challenge_cmd = on_command("挑战", priority=5, block=True)


@challenge_cmd.handle()
async def handle_challenge(
    bot: Bot, event: MessageEvent, arg: Message = CommandArg()
) -> None:
    if not isinstance(event, PrivateMessageEvent):
        await challenge_cmd.finish(_PRIVATE_ONLY)

    name = arg.extract_plain_text().strip()
    user_id = str(event.user_id)

    if not name:
        await challenge_cmd.finish(_OPPONENT_LIST_TEXT)
    if name not in OPPONENTS:
        await challenge_cmd.finish(f"❌ 未知对手：{name}\n{_OPPONENT_LIST_TEXT}")

    game, expired = games.get(user_id)
    if game is not None:
        await challenge_cmd.finish("你已有一局进行中，请先 /认输 或 /退出棋局。")
    if expired:
        await challenge_cmd.send("⚠️ 上一局因长时间未操作已自动结束。")

    opponent = OPPONENTS[name]
    config = GameConfig(
        user_color="white",
        mode="challenge",
        level_name=name,
        skill=opponent["skill"],
        movetime_ms=opponent["movetime"],
        depth=opponent["depth"],
        opponent_rating=opponent["rating"],
    )
    game = games.start(user_id, config)
    await _send_board(
        bot,
        event,
        game,
        f"⚔️ 挑战【{name}】（{opponent['rating']} 分）！你执白先行，祝你好运。",
    )


board_cmd = on_command("棋局", aliases={"棋盘", "board"}, priority=5, block=True)


@board_cmd.handle()
async def handle_board(bot: Bot, event: MessageEvent) -> None:
    if not isinstance(event, PrivateMessageEvent):
        await board_cmd.finish(_PRIVATE_ONLY)
    game, expired = games.get(str(event.user_id))
    if game is None:
        if expired:
            await board_cmd.finish("⚠️ 你的对局因长时间未操作已自动结束。")
        await board_cmd.finish("当前没有进行中的对局，发送 /国际象棋 开始一局吧~")
    await _send_board(bot, event, game)


undo_cmd = on_command("悔棋", priority=5, block=True)


@undo_cmd.handle()
async def handle_undo(bot: Bot, event: MessageEvent) -> None:
    if not isinstance(event, PrivateMessageEvent):
        await undo_cmd.finish(_PRIVATE_ONLY)
    await _undo_flow(bot, event, undo_cmd)


resign_cmd = on_command("认输", aliases={"投降"}, priority=5, block=True)


@resign_cmd.handle()
async def handle_resign(event: MessageEvent) -> None:
    if not isinstance(event, PrivateMessageEvent):
        await resign_cmd.finish(_PRIVATE_ONLY)
    await _resign_flow(event, resign_cmd)


quit_cmd = on_command("退出棋局", aliases={"弃权"}, priority=5, block=True)


@quit_cmd.handle()
async def handle_quit(event: MessageEvent) -> None:
    if not isinstance(event, PrivateMessageEvent):
        await quit_cmd.finish(_PRIVATE_ONLY)
    await _quit_flow(event, quit_cmd)


rank_cmd = on_command("排行榜", aliases={"分数榜"}, priority=5, block=True)


@rank_cmd.handle()
async def handle_rank(event: MessageEvent) -> None:
    if not isinstance(event, PrivateMessageEvent):
        await rank_cmd.finish(_PRIVATE_ONLY)
    ranking = get_leaderboard()
    if not ranking:
        await rank_cmd.finish("🏆 排行榜还是空的，快去 /挑战 一个对手上榜吧！")
    lines = ["🏆 国际象棋段位分排行榜"]
    for rank, record in ranking:
        tag = "（定级中）" if record.provisional else ""
        lines.append(
            f"{rank:>2}. {record.nickname or _mask_qq(record.user_id)} · "
            f"{record.rating} 分{tag}"
        )
    own = get_record(str(event.user_id))
    if own is not None:
        own_rank = get_rank(str(event.user_id))
        lines.append(f"\n你的排名：第 {own_rank} 名（{own.rating} 分）")
    await rank_cmd.finish("\n".join(lines))


score_cmd = on_command("我的分数", aliases={"我的段位", "分数"}, priority=5, block=True)


@score_cmd.handle()
async def handle_score(event: MessageEvent) -> None:
    if not isinstance(event, PrivateMessageEvent):
        await score_cmd.finish(_PRIVATE_ONLY)
    record = get_record(str(event.user_id))
    if record is None:
        await score_cmd.finish("你还没有进行过计分对局，发送 /挑战 <对手> 开始！")
    rank = get_rank(str(event.user_id))
    lines = [
        f"📊 你的段位分：{record.rating}",
        f"排名：第 {rank} 名" if rank else "",
        f"战绩：{record.wins} 胜 {record.draws} 和 {record.losses} 负"
        f"（共 {record.games} 局）",
        f"最高挑战：{_opponent_name(record.max_challenged) or '-'}"
        f"（{record.max_challenged or 0} 分）",
    ]
    if record.max_beaten:
        lines.append(
            f"最高击败：{_opponent_name(record.max_beaten)}（{record.max_beaten} 分）"
        )
    if record.provisional:
        remaining = get_settings().rating_provisional_games - record.games
        lines.append(f"定级期：还剩 {remaining} 局（期间分数变动更大）")
    await score_cmd.finish("\n".join(filter(None, lines)))


# ── 对局中的消息监听（优先级 9，block，仅私聊且有进行中对局） ──


def _in_active_game(event: MessageEvent) -> bool:
    if not isinstance(event, PrivateMessageEvent):
        return False
    game, _ = games.get(str(event.user_id))
    return game is not None


move_listener = on_message(rule=Rule(_in_active_game), priority=9, block=True)


@move_listener.handle()
async def handle_move_message(bot: Bot, event: MessageEvent) -> None:
    game, expired = games.get(str(event.user_id))
    if game is None:
        if expired:
            await move_listener.finish("⚠️ 你的对局因长时间未操作已自动结束。")
        return

    text = event.get_plaintext().strip()
    if not text:
        return

    # 对局中的口语指令
    if text in ("认输", "投降"):
        await _resign_flow(event, move_listener)
        return
    if text == "悔棋":
        await _undo_flow(bot, event, move_listener)
        return
    if text in ("退出", "退出棋局", "弃权", "不下了"):
        await _quit_flow(event, move_listener)
        return
    if text in ("棋局", "棋盘"):
        await _send_board(bot, event, game)
        return

    await _apply_turn(bot, event, game, text)
