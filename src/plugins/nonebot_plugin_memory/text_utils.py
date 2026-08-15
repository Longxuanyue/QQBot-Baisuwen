"""
文本处理工具：全项目分词/文本匹配的统一入口。

- normalize_text：输入归一化（全半角/表情/URL/叠字/标点）
- tokenize：jieba 分词（lru_cache 缓存 + 领域词典 + 动态词典）
- 领域词典 data/jieba_dict.txt：修复专名切分（明日方舟、流萤等）
- 动态词典：从群聊共现统计中学习新词，持久化到 user_data
- 别名扩展：data/aliases.json 内置别名 + 群 meta 级别名
"""

import functools
import json
import os
import re
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import jieba
    JIEBA_AVAILABLE = True
except ImportError:
    jieba = None
    JIEBA_AVAILABLE = False

# 数据目录（随仓库分发）
_DATA_DIR = Path(__file__).parent / "data"
DOMAIN_DICT_PATH = _DATA_DIR / "jieba_dict.txt"
ALIASES_PATH = _DATA_DIR / "aliases.json"

# 动态词典（运行时生成，不入库）
_DYNAMIC_DICT_DIR = os.getenv("MEMORY_USER_DATA_DIR", "user_data")
DYNAMIC_DICT_PATH = os.path.join(_DYNAMIC_DICT_DIR, "dynamic_jieba_dict.txt")

# ── 归一化 ──

_FULLWIDTH_MAP = str.maketrans(
    {chr(0xFF01 + i): chr(0x21 + i) for i in range(94)}
)
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]+"
)
_URL_RE = re.compile(r"https?://\S+")
_QQ_FACE_RE = re.compile(r"\[CQ:[^\]]+\]")
_QQ_IMG_RE = re.compile(r"\[图片\]|\[表情\]|\[动画表情\]|\[语音\]|\[视频\]|\[文件\]")
_DUP_CHAR_RE = re.compile(r"(.)\1{3,}")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """输入归一化：全角→半角、去表情/URL/QQ段、压缩叠字与空白。

    用于检索查询与匹配比较（不改变存储内容）。
    """
    if not text:
        return text
    text = _QQ_FACE_RE.sub(" ", text)
    text = _QQ_IMG_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    text = _EMOJI_RE.sub(" ", text)
    text = text.translate(_FULLWIDTH_MAP).lower()
    text = _DUP_CHAR_RE.sub("\\1", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


# ── 分词（带缓存） ──

@functools.lru_cache(maxsize=4096)
def tokenize(text: str) -> Tuple[str, ...]:
    """jieba 分词，过滤单字与停用词，返回 tuple（可缓存）"""
    if not text:
        return ()
    if not JIEBA_AVAILABLE:
        return tuple(re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", text))
    _ensure_dict_loaded()
    try:
        words = jieba.lcut(text)
    except Exception:
        return ()
    return tuple(w for w in words if len(w.strip()) >= 2)


# ── 词典加载 ──

_dynamic_words: set = set()
_dict_loaded = False
_dict_lock = threading.Lock()


def _ensure_dict_loaded() -> None:
    """加载静态领域词典 + 动态词典（幂等）"""
    global _dict_loaded
    if _dict_loaded or not JIEBA_AVAILABLE:
        return
    with _dict_lock:
        if _dict_loaded:
            return
        try:
            if DOMAIN_DICT_PATH.exists():
                jieba.load_userdict(str(DOMAIN_DICT_PATH))
            if os.path.exists(DYNAMIC_DICT_PATH):
                with open(DYNAMIC_DICT_PATH, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        word = line.split()[0]
                        jieba.add_word(word)
                        _dynamic_words.add(word)
        except Exception:
            pass
        _dict_loaded = True


def add_dynamic_word(word: str) -> bool:
    """学习一个新词：加入 jieba 词典并持久化（上限 1000 词，超出重写）"""
    global _dynamic_words
    if not JIEBA_AVAILABLE or not word or len(word) < 2:
        return False
    if word in _dynamic_words:
        return False
    _ensure_dict_loaded()
    try:
        jieba.add_word(word)
        _dynamic_words.add(word)
        os.makedirs(os.path.dirname(DYNAMIC_DICT_PATH), exist_ok=True)
        with open(DYNAMIC_DICT_PATH, "a", encoding="utf-8") as f:
            f.write(f"{word} 1000 n\n")
        # 上限保护：超过 1000 词重写为最后 1000 个
        if len(_dynamic_words) > 1000:
            words = sorted(_dynamic_words)[-1000:]
            with open(DYNAMIC_DICT_PATH, "w", encoding="utf-8") as f:
                for w in words:
                    f.write(f"{w} 1000 n\n")
            _dynamic_words = set(words)
        return True
    except Exception:
        return False


def learn_dynamic_dict() -> int:
    """（供群聊学习每日任务调用）占位：具体共现学习在 groupmind 实现"""
    _ensure_dict_loaded()
    return len(_dynamic_words)


# ── 别名扩展 ──

_aliases: Optional[Dict[str, List[str]]] = None


def load_aliases() -> Dict[str, List[str]]:
    """加载内置别名表：{主词: [别名...]}"""
    global _aliases
    if _aliases is not None:
        return _aliases
    _aliases = {}
    if ALIASES_PATH.exists():
        try:
            data = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _aliases = {
                    str(k): [str(v) for v in vs]
                    for k, vs in data.items()
                    if isinstance(vs, list)
                }
        except Exception:
            _aliases = {}
    return _aliases


def expand_query(query: str, extra_aliases: Optional[Dict[str, List[str]]] = None) -> List[str]:
    """查询扩展：返回 [原始词集, 扩展词集] 中的扩展词列表。

    若查询文本包含别名表中的主词或别名，则返回其所有同义词，
    用于 FTS/LIKE 的 OR 扩展。
    """
    norm = normalize_text(query)
    aliases = load_aliases()
    if extra_aliases:
        merged = dict(aliases)
        for k, vs in extra_aliases.items():
            merged.setdefault(k, [])
            merged[k] += vs
        aliases = merged
    extra: List[str] = []
    for main, alts in aliases.items():
        if main in norm or any(a in norm for a in alts):
            extra.append(main)
            extra.extend(alts)
    # 去重、去空、去自身
    seen = set()
    result = []
    for w in extra:
        w = w.strip()
        if w and w not in seen and w != norm:
            seen.add(w)
            result.append(w)
    return result


# ── 预热 ──

def warmup() -> None:
    """后台线程预热 jieba 词典，避免首条消息卡顿"""
    if not JIEBA_AVAILABLE:
        return

    def _worker():
        try:
            _ensure_dict_loaded()
            tokenize("白苏文记忆检索分词预热测试")
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True).start()


# 模块导入时启动预热
warmup()
