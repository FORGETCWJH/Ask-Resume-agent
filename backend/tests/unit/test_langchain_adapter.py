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


def test_json_mode_receives_schema_and_does_not_repair_network_failure(monkeypatch):
    from app.infrastructure.llm import LLMError
    import pytest
    messages = []

    class Provider:
        def __init__(self, **kwargs):
            pass

        def with_structured_output(self, schema, **kwargs):
            return self

        async def ainvoke(self, value):
            messages.append(value)
            raise TimeoutError("provider timeout")

    monkeypatch.setattr("app.infrastructure.llm.ChatOpenAI", Provider)
    adapter = LangChainOpenAIAdapter(base_url="https://example.test/v1", api_key="test", model="test", max_output_tokens=1000, timeout_seconds=1)
    with pytest.raises(LLMError):
        asyncio.run(adapter.structured(mode="questionGeneration", context="证据", user_text="生成", schema=QuestionGenerationResponse))
    assert len(messages) == 1, "网络失败不得当作结构化错误额外调用模型"
    assert '"properties"' in messages[0][0].content
