from app.dto.llm import StructuredResponse


def test_empty_feedback_variants_are_normalized():
    assert StructuredResponse.model_validate({"feedback": []}).feedback is None
    assert StructuredResponse.model_validate({"feedback": ""}).feedback is None
    assert StructuredResponse.model_validate({"feedback": {"strengths": ["有证据"]}}).feedback == {"strengths": ["有证据"]}


def test_provider_string_fields_are_normalized_to_structured_objects():
    response = StructuredResponse.model_validate(
        {
            "evidenceGaps": ["缺少具体 API 延迟指标"],
            "feedback": "回答覆盖了主要实现，但缺少失败场景。",
        }
    )
    assert response.evidence_gaps == [{"text": "缺少具体 API 延迟指标"}]
    assert response.feedback == {"text": "回答覆盖了主要实现，但缺少失败场景。"}


def test_provider_question_strings_are_normalized_to_question_objects():
    response = StructuredResponse.model_validate(
        {"questions": ["请解释缓存失效时的处理方式。", "为什么选择 Redis？"]}
    )
    assert response.questions == [
        {"text": "请解释缓存失效时的处理方式。"},
        {"text": "为什么选择 Redis？"},
    ]
