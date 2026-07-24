"""
辅助函数：依赖检查、音频格式验证等
"""

import importlib

def check_dependencies():
    """检查必要的 Python 包是否已安装"""
    required = ["whisper", "torch", "numpy", "soundfile"]
    missing = []
    for pkg in required:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        raise ImportError(f"缺少依赖: {missing}. 请安装: pip install {' '.join(missing)}")
    return True

def get_audio_duration(file_path):
    """获取音频文件时长（秒）"""
    import soundfile as sf
    info = sf.info(file_path)
    return info.duration