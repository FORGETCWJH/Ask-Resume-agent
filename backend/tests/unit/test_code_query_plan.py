import pytest

from app.infrastructure.code_query import QueryPlan, validate_query_plan


def test_query_plan_allows_relative_whitelisted_paths():
    plan = validate_query_plan({"keywords": ["Redis", "cache"], "paths": ["backend/app"], "maxFiles": 5})
    assert isinstance(plan, QueryPlan)
    assert plan.paths == ["backend/app"]
    assert plan.max_files == 5


@pytest.mark.parametrize("path", ["../", "C:/secret", "/etc", "backend/app; dir"])
def test_query_plan_rejects_path_escape_and_shell_syntax(path):
    with pytest.raises(ValueError):
        validate_query_plan({"keywords": ["cache"], "paths": [path]})


def test_query_plan_rejects_shell_commands_and_caps_limits():
    with pytest.raises(ValueError):
        validate_query_plan({"keywords": ["cache && del *"], "paths": ["."]})
    plan = validate_query_plan({"keywords": ["cache"], "paths": ["."], "maxFiles": 999, "maxBytes": 999999999})
    assert plan.max_files <= 30
    assert plan.max_bytes <= 200_000
