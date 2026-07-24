"""
参考音频索引 —— 从预构建的 index.json 加载，提供角色列表和切片查询。

数据来源: ref_audio/index.json（由 ref_audio/build_index.py 生成）
"""

import json
import os
import random
from difflib import SequenceMatcher
from typing import Optional


class ReferenceAudioIndex:
    """参考音频索引，提供角色列表和切片查询"""

    def __init__(self, index_path: Optional[str] = None):
        if index_path is None:
            # 相对于项目根目录的默认路径
            index_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__)
                )))),
                "ref_audio", "index.json"
            )

        with open(index_path, "r", encoding="utf-8") as f:
            self._data = json.load(f)

        self._characters: dict = self._data.get("characters", {})
        self._slices_cache: dict = {}  # {char_name: [slice, ...]}

        # 预计算：按角色分组切片，方便快速查询
        for name, entry in self._characters.items():
            self._slices_cache[name] = entry.get("slices", [])

    @property
    def characters(self) -> list[str]:
        """所有可用角色名"""
        return list(self._characters.keys())

    @property
    def total_slices(self) -> int:
        return self._data.get("total_slices", 0)

    @property
    def total_characters(self) -> int:
        return self._data.get("total_characters", 0)

    def has_character(self, name: str) -> bool:
        return name in self._characters

    def get_character_config(self, name: str) -> dict:
        """获取角色配置（tags, gender, keywords, emotions 等）"""
        entry = self._characters.get(name, {})
        return {
            "tags": entry.get("tags", []),
            "gender": entry.get("gender", "未知"),
            "keywords": entry.get("keywords", []),
            "emotions": entry.get("emotions", []),
            "has_full_audio": entry.get("has_full_audio", False),
        }

    def get_slices(self, character: str) -> list[dict]:
        """获取某角色的所有切片"""
        return self._slices_cache.get(character, [])

    def get_first_slice(self, character: str) -> Optional[dict]:
        """获取某角色的第一条切片（最常用）"""
        slices = self.get_slices(character)
        return slices[0] if slices else None

    def get_random_slice(self, character: str) -> Optional[dict]:
        """获取某角色的随机切片"""
        slices = self.get_slices(character)
        return random.choice(slices) if slices else None

    def find_best_slice(self, character: str, target_text: str, min_duration: float = 3.0) -> Optional[dict]:
        """
        从角色的切片中找到与目标文本最匹配的切片。

        匹配策略：
        1. 文本相似度（SequenceMatcher）
        2. 时长加分（3-5 秒的切片最理想）
        3. 返回综合得分最高的切片

        :param character: 角色名
        :param target_text: 目标合成文本
        :param min_duration: 最低时长要求（秒），GPT-SoVITS 推荐 3-10s
        :return: 最佳匹配切片，或 None
        """
        slices = self.get_slices(character)
        if not slices:
            return None

        best_slice = None
        best_score = -1.0

        for s in slices:
            # 文本相似度 (0~1)
            text_score = SequenceMatcher(None, target_text, s["text"]).ratio()

            # 时长加分：3-10 秒最理想，超出或不足则扣分
            dur = s.get("duration", 1.0)
            if 3.0 <= dur <= 10.0:
                dur_bonus = 0.3
            elif dur < 3.0:
                dur_bonus = -0.2 * (3.0 - dur)  # 每少1秒扣0.2
            else:
                dur_bonus = -0.1 * (dur - 10.0)  # 每多1秒扣0.1

            total_score = text_score + dur_bonus

            if total_score > best_score:
                best_score = total_score
                best_slice = s

        return best_slice

    def build_ref_path(self, slice_entry: dict) -> str:
        """
        将切片条目中的相对路径解析为绝对路径。

        :param slice_entry: 切片条目，包含 'path' 字段（相对于 ref_audio/）
        :return: 绝对文件路径
        """
        ref_audio_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)
            )))),
            "ref_audio"
        )
        return os.path.join(ref_audio_dir, slice_entry["path"])

    def __len__(self):
        return self.total_characters

    def __contains__(self, name: str) -> bool:
        return self.has_character(name)

    def __repr__(self):
        return f"<ReferenceAudioIndex: {self.total_characters} characters, {self.total_slices} slices>"
