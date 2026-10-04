import asyncio

from app.dto.llm import QuestionGenerationResponse
from app.infrastructure.llm import FakeLLMClient, LangChainOpenAIAdapter


def test_fake_llm_returns_task_specific_structured_response():
    result = asyncio.run(FakeLLMClient().structured(
        mode="questionGeneration",
        context="技能：Redis",
        user_text="生成问题",
        schema=QuestionGenerationResponse,
    ))
    assert isinstance(result, QuestionGenerationResponse)
    assert result.questions
    assert result.questions[0].text


def test_langchain_adapter_keeps_provider_configuration(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("app.infrastructure.llm.ChatOpenAI", FakeChatOpenAI)
    adapter = LangChainOpenAIAdapter(
        base_url="https://example.test/v1",
        api_key="secret",
        model="gpt-6-sol",
        max_output_tokens=64000,
        timeout_seconds=45,
    )
    adapter._build_model()
    assert captured == {
        "base_url": "https://example.test/v1",
        "api_key": "secret",
        "model": "gpt-6-sol",
        "max_tokens": 64000,
        "temperature": 0.2,
        "timeout": 45,
        "max_retries": 0,
    }
