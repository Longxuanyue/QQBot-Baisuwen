"""
策略3 角色路由器：三级降级策略自动选择最优角色。

策略层级：
  Level 1: 情感匹配 —— 分析回复文本的情感，匹配到情感相近的角色
  Level 2: 关键词匹配 —— 回复中出现角色关键词时匹配
  Level 3: 默认角色 —— 使用配置的 DEFAULT_CHARACTER
"""

import re
import random
import os
import json
from typing import Optional, Tuple

from .ref_audio_index import ReferenceAudioIndex


# ── 情感 → 角色映射 ──
# 从 characters.json 中提取，但这里也定义一份作为快速查找表
EMOTION_CHARACTER_MAP: dict = {
    "happy":   ["陈千语", "秋栗", "伊冯", "别礼", "莱万汀"],
    "sad":     ["艾尔黛拉", "艾维文娜", "安塔尔", "昼雪"],
    "angry":   ["孤光", "狼卫", "卡契尔", "阿列什", "骏卫"],
    "anxious": ["佩丽卡", "艾尔黛拉", "安塔尔"],
    "calm":    ["昼雪", "黎风", "安塔尔", "孤光", "佩丽卡", "萤石"],
    "excited": ["陈千语", "别礼", "莱万汀", "秋栗", "洁尔佩塔"],
    "neutral": [],
}


# ── 关键词 → 角色映射 ──
# 正则为每个角色配置特征词，用于 Level 2 匹配
KEYWORD_CHARACTER_RULES: list[Tuple[str, list[str]]] = [
    # (角色名, [关键词列表])
    ("陈千语",  ["剑", "武侠", "修炼", "侠客", "练剑", "剑招", "剑气", "招式", "拳法"]),
    ("艾尔黛拉", ["研究", "实验", "勘探", "前辈", "考察", "地质", "数据", "日记", "矿脉"]),
    ("孤光",    ["荒野", "天气", "自然", "风暴", "星空", "迁徙", "游历", "聚落", "兽"]),
    ("佩丽卡",  ["计划", "策略", "任务", "调配", "安排", "资源", "效率"]),
    ("秋栗",    ["甜点", "美食", "栗子", "蛋糕", "茶", "开心"]),
    ("萤石",    ["矿石", "矿脉", "资源", "采集"]),
    ("安塔尔",  ["治疗", "健康", "休息", "恢复", "放松", "药"]),
    ("莱万汀",  ["火焰", "燃烧", "灼热", "炎", "火"]),
    ("昼雪",    ["雪", "冬日", "寒冷", "冰", "安静"]),
    ("狼卫",    ["敌人", "进攻", "防守", "战术", "猎"]),
    ("赛希",    ["技术", "设备", "调试", "系统", "代码", "程序"]),
    ("女管理员", ["命令", "系统", "管理", "通知", "终端", "权限"]),
    ("男管理员", ["命令", "系统", "管理", "通知", "终端", "权限"]),
    ("黎风",    ["风", "自由", "逍遥", "旅途", "流浪"]),
    ("骏卫",    ["守卫", "巡逻", "骑士", "荣耀", "忠诚"]),
    ("别礼",    ["礼物", "庆祝", "节日", "畅快", "豪饮"]),
    ("大潘",    ["痛快", "帮忙", "兄弟", "豪迈"]),
    ("埃特拉",  ["艺术", "文化", "历史", "诗歌", "画"]),
    ("卡契尔",  ["分析", "观察", "谜", "秘密", "阴暗"]),
    ("余烬",    ["战术", "老兵", "战场", "余烬"]),
    ("伊冯",    ["关心", "照顾", "温柔", "呵护"]),
    ("洁尔佩塔",["时尚", "穿搭", "旅行", "光彩"]),
    ("艾维文娜",["音乐", "歌", "旋律", "演奏"]),
    ("阿列什",  ["守护", "安全", "保护", "巡逻", "警戒"]),
]


class CharacterRouter:
    """
    策略3：三级降级角色路由器。

    使用方式:
        router = CharacterRouter(index, sentiment_analyzer=_sentiment_analyzer)
        char_name, slice_info = router.route("我今天好开心啊！")
        # → ("陈千语", {"path": "...", "text": "...", ...})
    """

    def __init__(
        self,
        index: ReferenceAudioIndex,
        default_character: str = "陈千语",
        sentiment_analyzer=None,
    ):
        self.index = index
        self.default_character = default_character
        self._sentiment_analyzer = sentiment_analyzer

        # 验证默认角色存在
        if not index.has_character(default_character):
            available = index.characters
            if available:
                self.default_character = available[0]
            else:
                raise ValueError("No characters available in index")

        # 预编译关键词正则
        self._keyword_patterns: dict[str, re.Pattern] = {}
        for char_name, keywords in KEYWORD_CHARACTER_RULES:
            if index.has_character(char_name):
                pattern = "|".join(re.escape(kw) for kw in keywords)
                self._keyword_patterns[char_name] = re.compile(pattern)

    def route(self, text: str) -> Tuple[str, dict]:
        """
        根据文本内容路由到最合适的角色。

        :param text: LLM 生成的回复文本
        :return: (角色名, 切片字典 {path, text, lang, duration})
        """
        if not text or not text.strip():
            return self._fallback_default()

        # Level 1: 情感匹配
        char = self._emotion_match(text)
        if char:
            slice_info = self._pick_slice(char)
            if slice_info:
                return (char, slice_info)

        # Level 2: 关键词匹配
        char = self._keyword_match(text)
        if char:
            slice_info = self._pick_slice(char)
            if slice_info:
                return (char, slice_info)

        # Level 3: 默认角色
        return self._fallback_default()

    def _emotion_match(self, text: str) -> Optional[str]:
        """Level 1: 情感分析匹配"""
        if self._sentiment_analyzer is None:
            return None

        try:
            result = self._sentiment_analyzer.analyze(text)
        except Exception:
            return None

        emotion = result.get("emotion", "neutral")
        confidence = result.get("confidence", 0.0)

        # 仅在置信度足够高时使用情感匹配
        if confidence < 0.4 or emotion == "neutral":
            return None

        candidates = EMOTION_CHARACTER_MAP.get(emotion, [])
        if not candidates:
            return None

        # 选择候选列表中第一个在当前索引中存在的角色
        for c in candidates:
            if self.index.has_character(c):
                return c

        return None

    def _keyword_match(self, text: str) -> Optional[str]:
        """Level 2: 关键词匹配"""
        # 计算每个角色匹配到的关键词数
        scores: list[Tuple[str, int]] = []
        for char_name, pattern in self._keyword_patterns.items():
            matches = len(pattern.findall(text))
            if matches > 0:
                scores.append((char_name, matches))

        if not scores:
            return None

        # 取匹配数最多的角色
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[0][0]

    def _fallback_default(self) -> Tuple[str, dict]:
        """Level 3: 返回默认角色的随机切片"""
        slice_info = self._pick_slice(self.default_character)
        if slice_info is None:
            # 极度罕见：默认角色无切片
            # 遍历所有角色找到第一个有切片的
            for char in self.index.characters:
                slice_info = self._pick_slice(char)
                if slice_info:
                    return (char, slice_info)
            raise RuntimeError("No usable reference audio slices found!")
        return (self.default_character, slice_info)

    def _pick_slice(self, character: str) -> Optional[dict]:
        """
        为指定角色选择一个参考音频切片。

        优先选择 3-5 秒的切片（GPT-SoVITS 最佳范围），
        如果角色没有满足条件的切片，则使用第一条。

        :return: {"path": "相对路径", "text": "参考文本", "lang": "zh", "duration": 3.2}
        """
        slices = self.index.get_slices(character)
        if not slices:
            return None

        # 筛选 3-10 秒的切片
        ideal = [s for s in slices if 3.0 <= s.get("duration", 0) <= 10.0]
        if ideal:
            chosen = random.choice(ideal)
        else:
            # 如果所有切片都太短，尝试拼接取最长的
            best = max(slices, key=lambda s: s.get("duration", 0))
            if best.get("duration", 0) >= 1.5:
                chosen = best
            else:
                chosen = slices[0]  # 回退到第一条

        return {
            "path": self.index.build_ref_path(chosen),
            "text": chosen["text"],
            "lang": chosen.get("lang", "zh"),
            "duration": chosen.get("duration", 1.0),
            "character": character,
        }

    def get_available_characters(self) -> list[str]:
        """返回所有可用角色列表"""
        return self.index.characters

    def get_character_info(self, name: str) -> Optional[dict]:
        """获取角色的详细信息"""
        if not self.index.has_character(name):
            return None
        return self.index.get_character_config(name)
