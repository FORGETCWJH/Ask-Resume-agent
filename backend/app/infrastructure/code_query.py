"""模型只能提交结构化查询计划，执行器负责校验并限制读取范围。"""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class QueryPlan:
    keywords: list[str]
    paths: list[str]
    max_files: int = 20
    max_bytes: int = 100_000


def validate_query_plan(payload: dict) -> QueryPlan:
    keywords = [str(item).strip() for item in payload.get("keywords", []) if str(item).strip()]
    paths = [str(item).strip().replace("\\", "/") for item in payload.get("paths", ["."])]
    if not keywords or len(keywords) > 8 or any(_unsafe(item) for item in keywords):
        raise ValueError("query plan contains invalid keywords")
    if not paths or len(paths) > 8 or any(_unsafe_path(item) for item in paths):
        raise ValueError("query plan contains invalid paths")
    max_files = min(max(int(payload.get("maxFiles", 20)), 1), 30)
    max_bytes = min(max(int(payload.get("maxBytes", 100_000)), 1_000), 200_000)
    return QueryPlan(keywords=keywords, paths=paths, max_files=max_files, max_bytes=max_bytes)


def _unsafe(value: str) -> bool:
    return len(value) > 120 or any(token in value for token in ("&&", "||", ";", "`", "$(", "\n", "\r"))


def _unsafe_path(value: str) -> bool:
    return _unsafe(value) or value.startswith(("/", "\\")) or bool(re.match(r"^[A-Za-z]:", value)) or any(part == ".." for part in value.split("/"))
