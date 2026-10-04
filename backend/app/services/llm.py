"""旧导入兼容层；实际实现位于 infrastructure.llm。"""

from ..infrastructure.llm import LLMError, request_llm, request_resume_extraction

__all__ = ["LLMError", "request_llm", "request_resume_extraction"]
