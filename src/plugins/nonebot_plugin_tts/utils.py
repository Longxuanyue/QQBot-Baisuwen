
"""辅助工具：检查依赖、验证模型等"""

import importlib

def check_dependencies():
    """检查必要的 Python 包是否已安装"""
    required = ["torch", "numpy"]
    missing = []
    for pkg in required:
        if importlib.util.find_spec(pkg) is None:
            missing.append(pkg)
    if missing:
        raise ImportError(f"缺少依赖: {missing}. 请安装: pip install {' '.join(missing)}")
    return True