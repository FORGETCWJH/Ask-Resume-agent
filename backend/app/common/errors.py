from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppError(Exception):
    status: int
    code: str
    title: str
    detail: str
    type: str = "about:blank"
    field_errors: dict[str, list[str]] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(self.detail)

    def problem(self, trace_id: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {"type": self.type, "title": self.title, "status": self.status, "detail": self.detail, "code": self.code}
        if trace_id:
            result["traceId"] = trace_id
        if self.field_errors:
            result["fieldErrors"] = self.field_errors
        return result


def not_found(code: str, detail: str) -> AppError:
    return AppError(404, code, "Resource not found", detail)

