import asyncio
import json

import httpx

from ..config import settings
from ..dto.llm import StructuredResponse


class LLMError(RuntimeError):
    pass


async def request_resume_extraction(context: str) -> dict:
    """Request only redacted resume structure; callers validate the draft shape."""
    system = """你是简历结构化抽取器。只能从提供的脱敏证据中提取事实，不要补写不存在的信息。输出严格 JSON，顶层字段必须为 personalInfo、skills、workExperiences、projects。缺失字段使用空字符串、空数组或 null。"""
    payload = {
        "model": settings.llm_model,
        "temperature": 0,
        "max_tokens": settings.llm_max_output_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": context},
        ],
    }
    if settings.llm_response_format == "json_object":
        payload["response_format"] = {"type": "json_object"}
    headers = {settings.llm_api_key_header: settings.llm_api_key if settings.llm_auth_mode == "api-key" else f"Bearer {settings.llm_api_key}"}
    retryable_statuses = {429, 500, 502, 503, 504}
    async with httpx.AsyncClient(base_url=settings.llm_base_url.rstrip("/"), timeout=settings.llm_timeout_seconds) as client:
        for attempt in range(settings.llm_max_retries + 1):
            try:
                response = await client.post("/chat/completions", headers=headers, json=payload)
                if response.status_code in retryable_statuses and attempt < settings.llm_max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                response.raise_for_status()
                body = response.json()
                content = body["choices"][0]["message"]["content"]
                if isinstance(content, list):
                    content = "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in content)
                parsed = content if isinstance(content, dict) else json.loads(content)
                if not isinstance(parsed, dict):
                    raise TypeError("resume extraction must be an object")
                return parsed
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt >= settings.llm_max_retries:
                    raise LLMError(f"简历识别模型请求失败：{type(exc).__name__}") from exc
                await asyncio.sleep(0.5 * (attempt + 1))
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in retryable_statuses and attempt < settings.llm_max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise LLMError(f"简历识别模型返回 HTTP {exc.response.status_code}") from exc
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise LLMError(f"简历识别模型返回不是有效 JSON：{exc}") from exc
    raise LLMError("简历识别模型请求重试后仍失败")


def _demo_response(mode: str, evidence: list[dict], user_text: str) -> StructuredResponse:
    first = evidence[:3]
    citations = [{"evidence_id": item["id"], "quote": item["content"][:180], "location": item.get("source_path") or f"第 {item.get('page_number') or 1} 页"} for item in first]
    if mode in {"generate_questions", "generateQuestions"}:
        questions = [{"text": f"请详细解释这段经历中你亲自负责的部分：{item['content'][:80]}", "type": "implementation", "evidence_ids": [item["id"]]} for item in (first * 3)[:8]]
        return StructuredResponse(answer="已根据当前材料生成练习问题。", questions=questions, evidence=citations)
    return StructuredResponse(answer=f"当前为演示模式。你的问题是：{user_text}\n请结合材料中的证据补充具体做法、指标和取舍。", evidence=citations, evidence_gaps=[{"question": "你能补充一个可验证的结果指标吗？", "missing_detail": "材料中没有找到明确指标"}])


async def request_llm(mode: str, context: str, evidence: list[dict], user_text: str) -> StructuredResponse:
    if not settings.llm_api_key:
        return _demo_response(mode, evidence, user_text)
    system = """你是简历与项目面试练习助手。只能基于提供的证据回答。证据不足时提出澄清问题，不要编造数字、技术细节或经历。输出严格 JSON，字段为 answer、questions、evidence、inference_drafts、evidence_gaps、feedback。"""
    payload: dict = {
        "model": settings.llm_model,
        "temperature": settings.llm_temperature,
        "max_tokens": settings.llm_max_output_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"模式：{mode}\n材料和对话上下文：\n{context}\n\n当前问题：{user_text}"},
        ],
    }
    if settings.llm_response_format == "json_object":
        payload["response_format"] = {"type": "json_object"}
    if settings.llm_auth_mode == "api-key":
        headers = {settings.llm_api_key_header: settings.llm_api_key}
    else:
        headers = {settings.llm_api_key_header: f"Bearer {settings.llm_api_key}"}
    retryable_statuses = {429, 500, 502, 503, 504}
    content: str | dict | list
    async with httpx.AsyncClient(base_url=settings.llm_base_url.rstrip("/"), timeout=settings.llm_timeout_seconds) as client:
        for attempt in range(settings.llm_max_retries + 1):
            try:
                response = await client.post("/chat/completions", headers=headers, json=payload)
                if response.status_code in retryable_statuses and attempt < settings.llm_max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                response.raise_for_status()
                body = response.json()
                content = body["choices"][0]["message"]["content"]
                break
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt >= settings.llm_max_retries:
                    raise LLMError(f"模型请求失败：{type(exc).__name__}") from exc
                await asyncio.sleep(0.5 * (attempt + 1))
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                detail = "模型服务返回 HTTP 错误"
                if status in retryable_statuses and attempt < settings.llm_max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise LLMError(f"{detail}（HTTP {status}）") from exc
            except (KeyError, IndexError, TypeError) as exc:
                raise LLMError(f"模型响应缺少 choices[0].message.content：{exc}") from exc
        else:
            raise LLMError("模型请求重试后仍失败")
    try:
        if isinstance(content, list):
            content = "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in content)
        parsed = content if isinstance(content, dict) else json.loads(content)
        return StructuredResponse.model_validate(parsed)
    except Exception as exc:
        raise LLMError(f"模型返回不是有效结构化响应：{exc}") from exc
