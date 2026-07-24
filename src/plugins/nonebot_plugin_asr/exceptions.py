"""自定义异常"""

class ASRError(Exception):
    """ASR 模块基础异常"""
    pass

class ModelLoadError(ASRError):
    """模型加载失败"""
    pass

class RecognitionError(ASRError):
    """语音识别失败"""
    pass

class AudioInputError(ASRError):
    """音频输入无效"""
    pass