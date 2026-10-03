from app.config import Settings


def test_default_llm_output_token_limit_is_64000():
    settings = Settings(_env_file=None)

    assert settings.llm_max_output_tokens == 64000
