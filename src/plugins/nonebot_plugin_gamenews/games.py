"""
游戏配置 —— 白名单游戏元数据。

数据来源：tools/game-event-progress/data/{key}.json
排除游戏：胜利女神/无期迷途/尘白禁区/少女前线2/炉石传说/植物大战僵尸/永劫无间
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GameMeta:
    key: str          # JSON 文件名 stem
    name: str         # 中文显示名
    aliases: list[str] = field(default_factory=list)
    emoji: str = "🎮"
    color: str = "#f0c41a"  # 主题强调色


# ── 白名单（按显示顺序） ──

GAME_GENSHIN = "genshin"
GAME_STARRAIL = "starrail"
GAME_ZZZ = "zzz"
GAME_ARKNIGHTS = "arknights"
GAME_ENDFIELD = "endfield"
GAME_REVERSE1999 = "reverse1999"
GAME_AZURLANE = "azurlane"
GAME_BLUEARCHIVE = "bluearchive"
GAME_WUWA = "wuwa"
GAME_DELTA = "delta"

GAME_KEYS = [
    GAME_GENSHIN,
    GAME_STARRAIL,
    GAME_ZZZ,
    GAME_ARKNIGHTS,
    GAME_ENDFIELD,
    GAME_REVERSE1999,
    GAME_AZURLANE,
    GAME_BLUEARCHIVE,
    GAME_WUWA,
    GAME_DELTA,
]

GAMES: dict[str, GameMeta] = {
    GAME_GENSHIN: GameMeta(
        key=GAME_GENSHIN, name="原神",
        aliases=["原神", "ys", "genshin", "genshin impact"],
        emoji="🌿", color="#6ec8ff",
    ),
    GAME_STARRAIL: GameMeta(
        key=GAME_STARRAIL, name="崩坏：星穹铁道",
        aliases=["崩坏：星穹铁道", "崩坏:星穹铁道", "崩坏星穹铁道", "星穹铁道", "星铁", "崩铁", "sr", "starrail", "hkr"],
        emoji="🚂", color="#d4a574",
    ),
    GAME_ZZZ: GameMeta(
        key=GAME_ZZZ, name="绝区零",
        aliases=["绝区零", "zzz", "zenless", "zenless zone zero"],
        emoji="⚡", color="#ff6b6b",
    ),
    GAME_ARKNIGHTS: GameMeta(
        key=GAME_ARKNIGHTS, name="明日方舟",
        aliases=["明日方舟", "方舟", "ak", "arknights", "mrfz"],
        emoji="🏰", color="#f0c41a",
    ),
    GAME_ENDFIELD: GameMeta(
        key=GAME_ENDFIELD, name="明日方舟：终末地",
        aliases=["明日方舟：终末地", "明日方舟:终末地", "终末地", "ef", "endfield"],
        emoji="🌌", color="#9ad7c2",
    ),
    GAME_REVERSE1999: GameMeta(
        key=GAME_REVERSE1999, name="重返未来：1999",
        aliases=["重返未来：1999", "重返未来:1999", "重返未来1999", "重返未来", "1999", "r1999", "re1999"],
        emoji="⏳", color="#c9a87c",
    ),
    GAME_AZURLANE: GameMeta(
        key=GAME_AZURLANE, name="碧蓝航线",
        aliases=["碧蓝航线", "azurlane", "al", "blhx"],
        emoji="⚓", color="#5b8def",
    ),
    GAME_BLUEARCHIVE: GameMeta(
        key=GAME_BLUEARCHIVE, name="蔚蓝档案",
        aliases=["蔚蓝档案", "bluearchive", "ba", "ブルーアーカイブ"],
        emoji="🔫", color="#7eb6ff",
    ),
    GAME_WUWA: GameMeta(
        key=GAME_WUWA, name="鸣潮",
        aliases=["鸣潮", "wuwa", "ww", "wuthering waves"],
        emoji="🌊", color="#7dd3c0",
    ),
    GAME_DELTA: GameMeta(
        key=GAME_DELTA, name="三角洲行动",
        aliases=["三角洲行动", "三角洲", "delta", "delta force"],
        emoji="🔺", color="#ff8c42",
    ),
}

# 快捷映射
GAME_NAMES: dict[str, str] = {k: v.name for k, v in GAMES.items()}
GAME_EMOJIS: dict[str, str] = {k: v.emoji for k, v in GAMES.items()}

# 别名 → key
_ALIAS_MAP: dict[str, str] = {}
for _key, _cfg in GAMES.items():
    for _a in _cfg.aliases:
        _ALIAS_MAP.setdefault(_a.lower(), _key)


def _normalize(s: str) -> str:
    t = s.strip().lower()
    for full, half in {
        "：": ":", "（": "(", "）": ")", "，": ",",
        "！": "!", "？": "?", "；": ";", "　": " ",
    }.items():
        t = t.replace(full, half)
    return t


def resolve_game_key(user_input: str) -> str | None:
    """通过用户输入解析游戏 key。"""
    inp = _normalize(user_input)
    for alias, key in _ALIAS_MAP.items():
        if _normalize(alias) == inp:
            return key
    for alias, key in _ALIAS_MAP.items():
        if _normalize(alias) in inp or inp in _normalize(alias):
            return key
    return None
