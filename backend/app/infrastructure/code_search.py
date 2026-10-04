"""上传项目的安全、只读代码检索器。绝不执行代码或解析项目依赖。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .code_query import QueryPlan


@dataclass(frozen=True)
class CodeMatch:
    path: str
    line_start: int
    line_end: int
    snippet: str


class ReadOnlyCodeSearch:
    _ignored = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".idea"}
    _extensions = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".kt", ".sql", ".md", ".yml", ".yaml", ".json", ".xml", ".html", ".css"}

    def __init__(self, root: Path):
        self.root = root.resolve()

    def search(self, query: str, paths: list[str] | None = None, limit: int = 30) -> list[CodeMatch]:
        if not query.strip():
            return []
        roots = [self._safe_root(path) for path in (paths or ["."])]
        matches: list[CodeMatch] = []
        for base in roots:
            if not base:
                continue
            for file in base.rglob("*"):
                if len(matches) >= limit:
                    return matches
                if not file.is_file() or file.suffix.lower() not in self._extensions or self._is_ignored(file):
                    continue
                try:
                    lines = file.read_text(encoding="utf-8", errors="ignore").splitlines()
                except OSError:
                    continue
                for index, line in enumerate(lines, 1):
                    if query.casefold() in line.casefold():
                        relative = file.relative_to(self.root).as_posix()
                        matches.append(CodeMatch(relative, index, index, line.strip()[:600]))
                        if len(matches) >= limit:
                            return matches
        return matches

    def search_plan(self, plan: QueryPlan) -> list[CodeMatch]:
        matches: list[CodeMatch] = []
        total_bytes = 0
        for keyword in plan.keywords:
            for match in self.search(keyword, plan.paths, min(plan.max_files, plan.max_files - len(matches))):
                if any(existing.path == match.path and existing.line_start == match.line_start for existing in matches):
                    continue
                total_bytes += len(match.snippet.encode("utf-8"))
                if total_bytes > plan.max_bytes:
                    return matches
                matches.append(match)
                if len(matches) >= plan.max_files:
                    return matches
        return matches

    def _safe_root(self, path: str) -> Path | None:
        candidate = (self.root / path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            return None
        if self._is_ignored(candidate):
            return None
        return candidate if candidate.exists() else None

    def _is_ignored(self, path: Path) -> bool:
        return any(part in self._ignored for part in path.relative_to(self.root).parts) if path != self.root else False
