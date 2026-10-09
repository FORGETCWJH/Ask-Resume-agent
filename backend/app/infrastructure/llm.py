"""LangChain OpenAI-compatible LLM infrastructure adapter.

业务层只依赖本模块暴露的结构化调用入口。真实模型由 ChatOpenAI 适配，
测试和无 API Key 的本地演示使用 FakeLLMClient；应用层不直接发起 HTTP 请求。
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel
from pydantic import ValidationError
from langchain_core.exceptions import OutputParserException

try:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI
except ImportError:  # pragma: no cover - dependency installation is an environment concern
    HumanMessage = SystemMessage = None
    ChatOpenAI = None

from ..config import settings
from ..dto.llm import (
    FeedbackResponse,
    FollowUpQuestionResponse,
    QuestionGenerationResponse,
    QuestionItem,
    ReferenceAnswerResponse,
    StructuredResponse,
)

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """供应商、结构化输出或重试耗尽后的统一错误。"""


class LLMClient(Protocol):
    async def structured(
        self,
        *,
        mode: str,
        context: str,
        user_text: str,
        schema: type[T],
        system_prompt: str | None = None,
    ) -> T: ...


class LangChainOpenAIAdapter:
    """将 OpenAI-compatible 服务封装为 LangChain 结构化调用。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        max_output_tokens: int,
        timeout_seconds: float,
        temperature: float = 0.2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature

    def _build_model(self) -> Any:
        if ChatOpenAI is None:
            raise LLMError("langchain-openai 未安装")
        return ChatOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.model,
            max_tokens=self.max_output_tokens,
            temperature=self.temperature,
            timeout=self.timeout_seconds,
            max_retries=0,
        )

    async def structured(
        self,
        *,
        mode: str,
        context: str,
        user_text: str,
        schema: type[T],
        system_prompt: str | None = None,
    ) -> T:
        if HumanMessage is None or SystemMessage is None:
            raise LLMError("langchain-core 未安装")
        from ..domain.practice_intent import redact_context
        prompt = (system_prompt or _default_system_prompt(mode, schema)) + "\n必须遵循的 JSON Schema：\n" + json.dumps(schema.model_json_schema(by_alias=True), ensure_ascii=False)
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=redact_context(f"模式：{mode}\n上下文：\n{context}\n\n当前输入：{user_text}")),
        ]
        model = self._build_model()
        try:
            # json_mode 对 OpenAI-compatible 服务的兼容性高于 strict json_schema。
            runnable = model.with_structured_output(schema, method="json_mode")
            result = await runnable.ainvoke(messages)
            return schema.model_validate(result)
        except Exception as exc:
            if not isinstance(exc, (ValidationError, OutputParserException, json.JSONDecodeError)):
                raise LLMError(f"模型请求失败：{exc}") from exc
            # 一次修复请求只处理结构化失败；网络/供应商错误交给任务层显式重试。
            try:
                raw = await model.ainvoke(messages + [HumanMessage(content="请仅返回符合要求的 JSON 对象，不要输出 Markdown。")])
                parsed = _message_json(raw)
                return schema.model_validate(parsed)
            except Exception as repair_exc:
                raise LLMError(f"模型返回不是有效结构化响应：{repair_exc}") from exc


class FakeLLMClient:
    """自动化测试和无凭据本地演示使用的确定性实现。"""

    async def structured(
        self,
        *,
        mode: str,
        context: str,
        user_text: str,
        schema: type[T],
        system_prompt: str | None = None,
    ) -> T:
        from ..domain.practice_intent import PracticeIntent
        if schema is PracticeIntent:
            # 仅无凭据演示/自动化测试使用；真实环境始终走模型节点。
            payload = {"action": "answer", "answer": user_text}
            if "以后" in user_text or "本轮" in user_text:
                payload = {"action": "preference", "preferences": [{"key": "count", "value": 1, "scope": "longTerm" if "以后" in user_text else "round", "explicit": True, "instructionQuote": user_text}]}
            elif "生成" in user_text or "新一组" in user_text:
                match = re.search(r"(\d+)\s*(?:个|道)", user_text)
                payload = {"action": "regenerate" if "新一组" in user_text else "generate", "scope": {"count": int(match.group(1)) if match else 5, "topic": user_text}, "scopeOverrides": ["topic"] + (["count"] if match else [])}
            elif "下一题" in user_text:
                payload = {"action": "nextQuestion"}
            elif "追问" in user_text or "深入一点" in user_text:
                payload = {"action": "followUp"}
            elif "参考答案" in user_text:
                payload = {"action": "referenceAnswer"}
            elif "点评" in user_text or "反馈" in user_text:
                payload = {"action": "feedback", "answer": user_text.split("，请点评")[0] if "，请点评" in user_text else None}
            elif user_text == "换成消息队列":
                payload = {"outcome": "needsClarification", "clarification": "你希望换一组消息队列问题，还是继续追问当前题？"}
            return schema.model_validate(payload)
        if schema is QuestionGenerationResponse:
            match = re.search(r'"count"\s*:\s*(\d+)', context)
            count = min(int(match.group(1)), 20) if match else 1
            return schema.model_validate({"questions": [{"text": f"请解释你在该经历中亲自负责的核心部分（第 {index + 1} 题）。", "type": "implementation", "evidenceIds": []} for index in range(count)]})
        if schema is FeedbackResponse:
            return schema.model_validate({"summary": "回答已记录，请继续补充实现细节。", "strengths": ["回答聚焦当前问题"], "missingPoints": ["还缺少失败场景"], "nextPracticeStep": "补充一个具体排查过程。"})
        if schema is ReferenceAnswerResponse:
            return schema.model_validate({"answer": "当前没有代码证据，只能提供通用解释。", "evidenceGrade": "insufficient", "limitations": ["当前未启用代码证据"]})
        if schema is FollowUpQuestionResponse:
            return schema.model_validate({"question": "你能补充一个具体失败场景和排查步骤吗？", "reason": "当前回答缺少失败复盘"})
        if schema is StructuredResponse:
            return schema.model_validate(_demo_response(mode, [], user_text).model_dump())
        return schema.model_validate({})


def get_llm_client() -> LLMClient:
    if not settings.llm_api_key:
        return FakeLLMClient()
    return LangChainOpenAIAdapter(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        max_output_tokens=settings.llm_max_output_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
        temperature=settings.llm_temperature,
    )


async def request_llm(mode: str, context: str, evidence: list[dict], user_text: str) -> StructuredResponse:
    if not settings.llm_api_key:
        return _demo_response(mode, evidence, user_text)
    result = await get_llm_client().structured(
        mode=mode,
        context=context,
        user_text=user_text,
        schema=StructuredResponse,
        system_prompt=_default_system_prompt(mode, StructuredResponse),
    )
    return StructuredResponse.model_validate(result)


async def request_resume_extraction(context: str) -> dict[str, Any]:
    """保留 OCR 旧入口；当前 OCR 流程不主动调用此函数。"""

    result = await get_llm_client().structured(
        mode="resumeExtraction",
        context=context,
        user_text="提取简历模块",
        schema=StructuredResponse,
        system_prompt="只能从脱敏证据提取事实，输出 JSON，不得补写简历中不存在的信息。",
    )
    return result.model_dump(mode="json")


def _default_system_prompt(mode: str, schema: type[BaseModel]) -> str:
    return (
        "你是简历面试练习助手。只能基于输入证据回答，证据不足时必须明确说明，"
        "不得补写候选人的数字、技术细节或经历。只输出符合结构化 Schema 的 JSON 对象，"
        f"当前任务是 {mode}，响应模型是 {schema.__name__}。"
    )


def _message_json(message: Any) -> Any:
    content = getattr(message, "content", message)
    if isinstance(content, list):
        content = "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in content)
    if isinstance(content, dict):
        return content
    return json.loads(str(content).strip().removeprefix("```json").removesuffix("```").strip())


def _demo_response(mode: str, evidence: list[dict], user_text: str) -> StructuredResponse:
    citations = [{"evidence_id": item.get("id", ""), "quote": item.get("content", "")[:180], "location": item.get("source_path") or "原文"} for item in evidence[:3]]
    if mode in {"generate_questions", "generateQuestions"}:
        questions = [QuestionItem(text="请解释你在该经历中亲自负责的核心部分。", type="implementation")]
        return StructuredResponse(answer="已根据当前材料生成练习问题。", questions=[item.model_dump() for item in questions], evidence=citations)
    return StructuredResponse(answer=f"当前为演示模式。你的问题是：{user_text}", evidence=citations, evidence_gaps=[{"question": "请补充一个可以验证的结果或排查过程。", "missing_detail": "演示模型没有从当前回答中找到明确证据。"}])
