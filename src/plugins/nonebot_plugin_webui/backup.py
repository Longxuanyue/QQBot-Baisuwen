"""
备份与恢复：一键打包下载 / 上传恢复
"""

import json
import os
import shutil
import tempfile
import time
import zipfile
from io import BytesIO
from typing import Optional

from nonebot import logger

from .config import PLUGIN_STATES_FILE, ENV_BACKUP_DIR, DATA_DIR


def _get_project_root() -> str:
    """项目根目录（baisuwen/）"""
    return os.path.dirname(DATA_DIR)


def create_backup(include_memory: bool = False) -> Optional[BytesIO]:
    """
    创建备份 ZIP 包。

    :param include_memory: 是否包含记忆数据（user_data/*.db）
    :return: BytesIO 或 None（失败时）
    """
    root = _get_project_root()
    buf = BytesIO()

    try:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # .env
            env_path = os.path.join(root, ".env")
            if os.path.exists(env_path):
                zf.write(env_path, ".env")

            # 人设文件
            personality_path = os.path.join(
                root, "src/plugins/nonebot_plugin_update_baisuwen/personality_traits.json"
            )
            if os.path.exists(personality_path):
                zf.write(personality_path, "personality_traits.json")

            # 插件开关状态
            if os.path.exists(PLUGIN_STATES_FILE):
                zf.write(PLUGIN_STATES_FILE, "webui_plugin_states.json")

            # 用户角色
            users_file = os.path.join(DATA_DIR, "webui_users.json")
            if os.path.exists(users_file):
                zf.write(users_file, "webui_users.json")

            # 记忆数据（可选）
            if include_memory:
                user_data_dir = os.path.join(root, "user_data")
                if os.path.isdir(user_data_dir):
                    for fname in os.listdir(user_data_dir):
                        if fname.endswith(".db"):
                            fpath = os.path.join(user_data_dir, fname)
                            zf.write(fpath, f"user_data/{fname}")

            # 元信息
            meta = {
                "backup_time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "include_memory": include_memory,
                "files": [f.filename for f in zf.filelist],
            }
            zf.writestr("backup_meta.json", json.dumps(meta, ensure_ascii=False, indent=2))

        buf.seek(0)
        return buf
    except Exception as e:
        logger.error(f"创建备份失败: {e}")
        return None


def restore_backup(zip_data: bytes) -> dict:
    """
    从上传的 ZIP 恢复配置。

    返回: {"ok": bool, "message": str, "restored_files": list[str]}
    """
    root = _get_project_root()
    tmp_dir = tempfile.mkdtemp(prefix="webui_restore_")
    restored = []
    backups_made = []

    try:
        # 解压到临时目录
        with zipfile.ZipFile(BytesIO(zip_data), "r") as zf:
            zf.extractall(tmp_dir)

        # 验证备份包
        meta_path = os.path.join(tmp_dir, "backup_meta.json")
        if not os.path.exists(meta_path):
            return {"ok": False, "message": "无效的备份包：缺少 backup_meta.json", "restored_files": []}

        # 恢复 .env
        src_env = os.path.join(tmp_dir, ".env")
        if os.path.exists(src_env):
            dst_env = os.path.join(root, ".env")
            if os.path.exists(dst_env):
                backup_path = _backup_file(dst_env)
                backups_made.append(backup_path)
            shutil.copy2(src_env, dst_env)
            restored.append(".env")

        # 恢复人设
        src_personality = os.path.join(tmp_dir, "personality_traits.json")
        if os.path.exists(src_personality):
            dst_personality = os.path.join(
                root, "src/plugins/nonebot_plugin_update_baisuwen/personality_traits.json"
            )
            if os.path.exists(dst_personality):
                _backup_file(dst_personality)
            os.makedirs(os.path.dirname(dst_personality), exist_ok=True)
            shutil.copy2(src_personality, dst_personality)
            restored.append("personality_traits.json")

        # 恢复插件状态
        src_states = os.path.join(tmp_dir, "webui_plugin_states.json")
        if os.path.exists(src_states):
            if os.path.exists(PLUGIN_STATES_FILE):
                _backup_file(PLUGIN_STATES_FILE)
            os.makedirs(os.path.dirname(PLUGIN_STATES_FILE), exist_ok=True)
            shutil.copy2(src_states, PLUGIN_STATES_FILE)
            restored.append("webui_plugin_states.json")

        # 恢复记忆（合并，不覆盖）
        src_user_data = os.path.join(tmp_dir, "user_data")
        if os.path.isdir(src_user_data):
            dst_user_data = os.path.join(root, "user_data")
            os.makedirs(dst_user_data, exist_ok=True)
            for fname in os.listdir(src_user_data):
                src = os.path.join(src_user_data, fname)
                dst = os.path.join(dst_user_data, fname)
                if os.path.exists(dst):
                    # 备份现有文件
                    _backup_file(dst)
                shutil.copy2(src, dst)
                restored.append(f"user_data/{fname}")

        return {
            "ok": True,
            "message": f"成功恢复 {len(restored)} 个文件。备份保存在 {ENV_BACKUP_DIR}",
            "restored_files": restored,
        }

    except Exception as e:
        # 回滚：恢复备份
        logger.error(f"恢复失败: {e}")
        for backup_path in backups_made:
            try:
                original = backup_path.replace(".bak.", ".")
                # 从备份路径提取原始路径
                shutil.copy2(backup_path, original.replace(f".bak.{_extract_ts(backup_path)}", ""))
            except Exception:
                pass
        return {"ok": False, "message": f"恢复失败: {e}", "restored_files": []}

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _backup_file(filepath: str) -> str:
    """备份文件到 ENV_BACKUP_DIR"""
    os.makedirs(ENV_BACKUP_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    fname = os.path.basename(filepath)
    backup_path = os.path.join(ENV_BACKUP_DIR, f"{fname}.bak.{ts}")
    shutil.copy2(filepath, backup_path)
    return backup_path


def _extract_ts(path: str) -> str:
    """从备份路径提取时间戳"""
    parts = path.rsplit(".", 1)
    return parts[-1] if len(parts) > 1 else ""
