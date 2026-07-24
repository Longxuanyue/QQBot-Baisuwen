"""自定义异常"""

class TTSException(Exception):
    """TTS 模块基础异常"""
    pass

class ModelLoadError(TTSException):
    """模型加载失败"""
    pass

class SynthesisError(TTSException):
    """语音合成失败"""
    pass

class ProcessingError(TTSException):
    """文本处理错误"""
    pass