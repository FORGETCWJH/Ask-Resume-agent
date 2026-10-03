"""OpenAI-compatible LLM 基础设施适配器。"""

from ..services.llm import LLMError, request_llm, request_resume_extraction

__all__ = ["LLMError", "request_llm", "request_resume_extraction"]
