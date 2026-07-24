"""
情感分析引擎

支持规则匹配和 LLM 两种分析方式。
"""

import re
from typing import Dict, Any, Optional
from nonebot import logger

from .config import (
    ENABLE_SENTIMENT, SENTIMENT_MODE,
    POSITIVE_WORDS, NEGATIVE_WORDS, EMOTION_LABELS
)


class SentimentAnalyzer:
    """情感分析器"""

    def __init__(self, llm_client=None):
        self._llm_client = llm_client

    def set_llm_client(self, llm_client):
        """注入 LLM 客户端（用于 LLM 模式分析）"""
        self._llm_client = llm_client

    def analyze(self, text: str) -> Dict[str, Any]:
        """
        分析文本情感，返回:
        {
            "sentiment": "positive" | "negative" | "neutral",
            "emotion": "happy" | "sad" | "angry" | "anxious" | "calm" | "excited" | "neutral",
            "confidence": 0.0 ~ 1.0,
            "scores": {"positive": 0.8, "negative": 0.1, ...}
        }
        """
        if not ENABLE_SENTIMENT:
            return self._neutral_result()

        if SENTIMENT_MODE in ("rule", "both"):
            result = self._rule_analyze(text)
            if SENTIMENT_MODE == "rule" or result["confidence"] >= 0.6:
                return result

        return self._neutral_result()

    async def analyze_llm(self, text: str) -> Dict[str, Any]:
        """使用 LLM 进行情感分析"""
        if self._llm_client is None:
            return self._neutral_result()

        prompt = f"""分析以下文本的情感，返回 JSON 格式：
{{
    "emotion": "happy/sad/angry/anxious/calm/excited/neutral",
    "confidence": 0.0-1.0
}}

文本：{text}

只返回 JSON:"""

        try:
            response = await self._llm_client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=50
            )
            import json
            result = json.loads(response.strip())
            emotion = result.get("emotion", "neutral")
            confidence = float(result.get("confidence", 0.5))
            sentiment = self._emotion_to_sentiment(emotion)
            return {
                "sentiment": sentiment,
                "emotion": emotion,
                "confidence": min(1.0, max(0.0, confidence)),
                "scores": {e: 0.1 for e in EMOTION_LABELS},
            }
        except Exception as e:
            logger.debug(f"LLM 情感分析失败: {e}")
            return self._neutral_result()

    def _rule_analyze(self, text: str) -> Dict[str, Any]:
        """基于规则的情感分析"""
        text_lower = text.lower()

        pos_count = sum(1 for w in POSITIVE_WORDS if w in text_lower)
        neg_count = sum(1 for w in NEGATIVE_WORDS if w in text_lower)

        # 检测表情符号
        happy_emoji = bool(re.search(r'[😊😄😁😆😂🤣🥰😍😘😋😎✨🎉💕👍]', text))
        sad_emoji = bool(re.search(r'[😢😭😞😔😟😩😫😤😡🤬💔👎😿]', text))

        if happy_emoji:
            pos_count += 2
        if sad_emoji:
            neg_count += 2

        total = pos_count + neg_count
        if total == 0:
            return self._neutral_result()

        pos_score = pos_count / max(total, 1)

        # 确定情感
        if pos_score >= 0.7:
            sentiment = "positive"
            emotion = "happy" if "兴奋" in text or "激动" in text or happy_emoji else "calm"
        elif pos_score <= 0.3:
            sentiment = "negative"
            if "生气" in text or "愤怒" in text or sad_emoji:
                emotion = "angry"
            elif "焦虑" in text or "紧张" in text or "害怕" in text:
                emotion = "anxious"
            else:
                emotion = "sad"
        else:
            sentiment = "neutral"
            emotion = "neutral"

        return {
            "sentiment": sentiment,
            "emotion": emotion,
            "confidence": min(0.9, total / 8.0),
            "scores": {
                "positive": pos_score,
                "negative": 1.0 - pos_score,
            },
        }

    def get_emotional_context(self, text: str) -> str:
        """获取情感上下文文本（用于注入到 system prompt 中）"""
        result = self.analyze(text)
        emotion = result["emotion"]
        confidence = result["confidence"]

        if confidence < 0.5:
            return ""

        hints = {
            "happy": "用户现在心情很好，你可以保持轻松愉快的语气。",
            "sad": "用户似乎有些难过或低落，请用温柔体贴的语气安慰TA。",
            "angry": "用户现在可能有些生气或不满，请保持冷静和耐心，不要激化情绪。",
            "anxious": "用户可能有些焦虑或紧张，请用平静安稳的语气让TA放松。",
            "calm": "用户现在比较平静，正常交流即可。",
            "excited": "用户现在很兴奋，你可以同样热情地回应。",
            "neutral": "",
        }

        return hints.get(emotion, "")

    @staticmethod
    def _emotion_to_sentiment(emotion: str) -> str:
        positive = {"happy", "excited", "calm"}
        negative = {"sad", "angry", "anxious"}
        if emotion in positive:
            return "positive"
        elif emotion in negative:
            return "negative"
        return "neutral"

    @staticmethod
    def _neutral_result() -> Dict[str, Any]:
        return {
            "sentiment": "neutral",
            "emotion": "neutral",
            "confidence": 0.0,
            "scores": {"positive": 0.33, "negative": 0.33, "neutral": 0.34},
        }


# 全局实例
sentiment_analyzer = SentimentAnalyzer()
