"""
用户画像构建引擎

从用户记忆库中提取结构化用户特征，生成画像摘要。
"""

import sqlite3
import os
import time
from typing import Dict, List, Optional, Any
from collections import defaultdict

from nonebot import logger

from .config import PROFILE_MAX_WORDS, PROFILE_UPDATE_INTERVAL

try:
    import jieba
    JIEBA_AVAILABLE = True
except ImportError:
    JIEBA_AVAILABLE = False


class UserProfiler:
    """用户画像构建器"""

    def __init__(self, user_data_dir: str = "user_data"):
        self.user_data_dir = user_data_dir
        self._profile_cache: Dict[str, Dict[str, Any]] = {}

    def _get_db_path(self, user_id: str, db_type: str = "short") -> str:
        return os.path.join(self.user_data_dir, f"{db_type}_{user_id}.db")

    def get_all_memories(self, user_id: str) -> List[str]:
        """获取用户所有记忆内容"""
        contents = []
        for db_type in ("short", "long"):
            db_path = self._get_db_path(user_id, db_type)
            if not os.path.exists(db_path):
                continue
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT content FROM memories ORDER BY importance DESC LIMIT 500"
            )
            for (content,) in cursor.fetchall():
                contents.append(content)
            conn.close()
        return contents

    def extract_basic_info(self, user_id: str) -> Dict[str, str]:
        """通过规则提取用户基本信息（姓名、所在地等）"""
        import re
        info: Dict[str, str] = {}
        memories = self.get_all_memories(user_id)

        patterns = {
            "name": [
                r"(?:我(?:的)?名字?是?叫?|我是)\s*(.+?)(?:[。，,\.;；!！？?\s]|$)",
                r"(?:叫我|称呼我为)\s*(.+?)(?:[。，,\.;；!！？?\s]|$)",
            ],
            "location": [
                r"(?:我(?:住|生活在|在))\s*(.+?)(?:[。，,\.;；!！？?\s]|$)",
                r"(?:来自)\s*(.+?)(?:[。，,\.;；!！？?\s]|$)",
            ],
            "occupation": [
                r"(?:我(?:是|是一名|做|从事))\s*(.+?)(?:[。，,\.;；!！？?\s]|$)",
            ],
        }

        for field, field_patterns in patterns.items():
            for content in memories:
                for pattern in field_patterns:
                    m = re.search(pattern, content)
                    if m:
                        val = m.group(1).strip()
                        if 1 < len(val) < 20:
                            info[field] = val
                            break
                if field in info:
                    break

        return info

    def extract_preferences(self, user_id: str) -> Dict[str, List[str]]:
        """通过规则提取用户偏好（喜欢/不喜欢）"""
        import re
        prefs: Dict[str, List[str]] = {"likes": [], "dislikes": []}
        memories = self.get_all_memories(user_id)

        like_pattern = re.compile(r"(?:喜欢|喜爱|爱|最爱|偏好)\s*(.+?)(?:[。，,\.;；!！？?\s]|$)")
        dislike_pattern = re.compile(r"(?:讨厌|不喜欢|厌恶|不爱)\s*(.+?)(?:[。，,\.;；!！？?\s]|$)")

        for content in memories:
            m = like_pattern.search(content)
            if m:
                val = m.group(1).strip()
                if 2 <= len(val) <= 30 and val not in prefs["likes"]:
                    prefs["likes"].append(val)
            m = dislike_pattern.search(content)
            if m:
                val = m.group(1).strip()
                if 2 <= len(val) <= 30 and val not in prefs["dislikes"]:
                    prefs["dislikes"].append(val)

        return prefs

    def extract_top_keywords(self, user_id: str, top_n: int = 20) -> List[str]:
        """从记忆中提取高频关键词"""
        if not JIEBA_AVAILABLE:
            return []
        memories = self.get_all_memories(user_id)
        word_counts: Dict[str, int] = defaultdict(int)
        stopwords = {"我", "你", "他", "她", "它", "的", "了", "是", "在", "和",
                     "就", "都", "也", "很", "要", "会", "有", "不", "这", "那",
                     "吗", "呢", "吧", "啊", "哦", "嗯", "呀", "哈"}

        for content in memories:
            words = jieba.lcut(content)
            for w in words:
                if len(w) >= 2 and w not in stopwords:
                    word_counts[w] += 1

        sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
        return [w for w, _ in sorted_words[:top_n]]

    def build_profile(self, user_id: str) -> Dict[str, Any]:
        """构建完整用户画像"""
        basic_info = self.extract_basic_info(user_id)
        preferences = self.extract_preferences(user_id)
        keywords = self.extract_top_keywords(user_id)
        all_memories = self.get_all_memories(user_id)

        profile = {
            "user_id": user_id,
            "basic_info": basic_info,
            "preferences": preferences,
            "top_keywords": keywords,
            "memory_count": len(all_memories),
            "updated_at": time.time(),
        }

        # 缓存
        self._profile_cache[user_id] = profile
        return profile

    def get_profile_summary(self, user_id: str) -> str:
        """生成画像文本摘要（用于注入 system prompt）"""
        profile = self._profile_cache.get(user_id)
        if profile is None:
            profile = self.build_profile(user_id)

        lines = []
        mem_count = profile.get("memory_count", 0)
        lines.append(f"该用户共有 {mem_count} 条记忆。")

        basic = profile.get("basic_info", {})
        if basic:
            info_parts = []
            for field, label in [("name", "姓名"), ("location", "所在地"),
                                 ("occupation", "职业")]:
                if field in basic:
                    info_parts.append(f"{label}: {basic[field]}")
            if info_parts:
                lines.append("基本信息: " + "，".join(info_parts))

        prefs = profile.get("preferences", {})
        likes = prefs.get("likes", [])
        dislikes = prefs.get("dislikes", [])
        if likes:
            lines.append(f"喜欢: {'、'.join(likes[:5])}")
        if dislikes:
            lines.append(f"不喜欢: {'、'.join(dislikes[:5])}")

        keywords = profile.get("top_keywords", [])
        if keywords:
            lines.append(f"关注话题: {'、'.join(keywords[:10])}")

        return "\n".join(lines)


# 全局实例
profiler = UserProfiler()
