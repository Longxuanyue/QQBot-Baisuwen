from typing import List, Dict, Any, Optional
from .data_manager import get_all_entries, get_name_index, get_id_index


def search_by_id(eid: str) -> Optional[Dict[str, Any]]:
    """按编号精确查询"""
    return get_id_index().get(eid)


def search_by_name(name: str) -> List[Dict[str, Any]]:
    """按名称精确查询，返回所有同名条目列表"""
    return get_name_index().get(name, [])


def search_by_tags(tags: List[str]) -> List[Dict[str, Any]]:
    """按标签查询，所有标签都必须匹配（AND）"""
    results = []
    for entry in get_all_entries():
        sub_tags = entry.get("subTags", [])
        if all(tag in sub_tags for tag in tags):
            results.append(entry)
    return results


def search_mixed(keywords: List[str]) -> List[Dict[str, Any]]:
    """
    混合查询：每个关键词可以是名称、ID 或标签，所有关键词必须匹配（AND）。
    """
    results = []
    for entry in get_all_entries():
        # 构建该条目的可搜索集合
        search_pool = {entry.get("name", ""), entry.get("id", "")}
        search_pool.update(entry.get("subTags", []))
        if all(kw in search_pool for kw in keywords):
            results.append(entry)
    return results