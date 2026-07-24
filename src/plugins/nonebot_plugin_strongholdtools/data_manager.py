import json
from pathlib import Path
from typing import List, Dict, Any, Optional

PLUGIN_DIR = Path(__file__).parent
DATA_FILE = PLUGIN_DIR / "data" / "enemy_entries.json"
IMAGE_DIR = PLUGIN_DIR / "images"

# 全局缓存
_enemy_data: Optional[List[Dict[str, Any]]] = None
_name_to_entries: Dict[str, List[Dict[str, Any]]] = {}
_id_to_entry: Dict[str, Dict[str, Any]] = {}


def load_data():
    """加载 JSON 数据并建立索引（仅执行一次）"""
    global _enemy_data, _name_to_entries, _id_to_entry
    if _enemy_data is not None:
        return

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise RuntimeError(f"无法加载敌人数据文件 {DATA_FILE}: {e}")

    _enemy_data = data.get("entries", [])
    for entry in _enemy_data:
        name = entry.get("name", "")
        if name:
            _name_to_entries.setdefault(name, []).append(entry)
        eid = entry.get("id", "")
        if eid:
            _id_to_entry[eid] = entry


def get_all_entries() -> List[Dict[str, Any]]:
    load_data()
    return _enemy_data


def get_name_index() -> Dict[str, List[Dict[str, Any]]]:
    load_data()
    return _name_to_entries


def get_id_index() -> Dict[str, Dict[str, Any]]:
    load_data()
    return _id_to_entry


def find_image_path(entry_name: str, entry_id: str) -> Optional[Path]:
    """
    根据敌人名称直接查找同名 .png 图片。
    图片文件名已标准化为与敌人 name 字段一致（包括引号、空格等）。
    """
    if not IMAGE_DIR.exists():
        return None

    # 直接拼接 name.png
    img_path = IMAGE_DIR / f"{entry_name}.png"
    if img_path.exists():
        return img_path

    # 如果没找到，可记录日志，但此处不处理，返回 None
    return None