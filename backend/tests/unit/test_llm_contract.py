from app.dto.llm import StructuredResponse


def test_empty_feedback_variants_are_normalized():
    assert StructuredResponse.model_validate({"feedback": []}).feedback is None
    assert StructuredResponse.model_validate({"feedback": ""}).feedback is None
    assert StructuredResponse.model_validate({"feedback": {"strengths": ["有证据"]}}).feedback == {"strengths": ["有证据"]}
