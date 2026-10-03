import io
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from fastapi import UploadFile
from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from ..config import settings
from ..common.errors import AppError
from ..models import EvidenceChunk, Material


TEXT_EXTENSIONS = {
    ".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".xml", ".sql", ".html", ".css", ".js", ".ts", ".tsx", ".java", ".go",
    ".rs", ".sh", ".bat", ".dockerfile", ".env.example",
}
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[^\s'\"]+"),
    re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----.*?-----END [A-Z ]+ PRIVATE KEY-----", re.S),
]


def _redact(value: str) -> str:
    for pattern in SECRET_PATTERNS:
        value = pattern.sub("[已脱敏内容]", value)
    return value


def _chunks(content: str, size: int = 2500, overlap: int = 200) -> list[str]:
    normalized = content.strip()
    if not normalized:
        return []
    result: list[str] = []
    start = 0
    while start < len(normalized):
        result.append(normalized[start:start + size])
        start += size - overlap
    return result


def _add_evidence(db: Session, material: Material, content: str, source_path: str | None = None, page: int | None = None) -> None:
    last_order = db.query(EvidenceChunk.chunk_order).filter(EvidenceChunk.material_id == material.id).order_by(EvidenceChunk.chunk_order.desc()).first()
    next_order = (last_order[0] + 1) if last_order and last_order[0] is not None else 0
    for index, chunk in enumerate(_chunks(_redact(content))):
        evidence = EvidenceChunk(material_id=material.id, content=chunk, source_path=source_path, page_number=page, chunk_order=next_order + index)
        db.add(evidence)
        db.flush()
        db.execute(text("INSERT INTO evidence_fts(evidence_id, content, source_path) VALUES (:id, :content, :path)"), {"id": evidence.id, "content": chunk, "path": source_path or ""})


def _extract_pdf_pages(path: Path, page_number: int | None = None) -> tuple[list[tuple[str, int]], list[dict[str, str | int]]]:
    import fitz

    pages: list[tuple[str, int]] = []
    warnings: list[dict[str, str | int]] = []
    try:
        document = fitz.open(path)
    except Exception as exc:
        return [], [{"code": "PDF_PARSE_FAILED", "message": f"PDF 解析失败：{str(exc)[:300]}"}]
    if page_number is not None and (page_number < 1 or page_number > document.page_count):
        document.close()
        return [], [{"code": "PAGE_NOT_FOUND", "pageNumber": page_number, "message": f"第 {page_number} 页不存在"}]
    for number, page in enumerate(document, start=1):
        if page_number is not None and number != page_number:
            continue
        page_text = page.get_text("text").strip()
        if page_text:
            pages.append((page_text, number))
            continue
        try:
            from PIL import Image
            from rapidocr_onnxruntime import RapidOCR

            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            result, _ = RapidOCR()(image)
            ocr_text = "\n".join(item[1] for item in (result or []))
            if ocr_text.strip():
                pages.append((ocr_text, number))
            else:
                warnings.append({"code": "OCR_PAGE_EMPTY", "pageNumber": number, "message": f"第 {number} 页未识别出文本"})
        except Exception:
            warnings.append({"code": "OCR_PAGE_FAILED", "pageNumber": number, "message": f"第 {number} 页 OCR 失败，可单独重试"})
    document.close()
    return pages, warnings


def _extract_pdf(path: Path) -> list[tuple[str, int]]:
    """Compatibility helper retained for callers that only need successful pages."""
    pages, _ = _extract_pdf_pages(path)
    return pages


def _extract_docx(path: Path) -> str:
    document = Document(path)
    parts: list[str] = []
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            paragraph = Paragraph(child, document)
            if paragraph.text.strip():
                parts.append(paragraph.text.strip())
        elif child.tag.endswith("}tbl"):
            table = Table(child, document)
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
    return "\n".join(parts)


async def save_upload(upload: UploadFile, destination: Path, max_bytes: int = settings.max_upload_bytes) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with destination.open("wb") as handle:
        while chunk := await upload.read(1024 * 1024):
            total += len(chunk)
            if total > max_bytes:
                handle.close()
                destination.unlink(missing_ok=True)
                raise AppError(413, "UPLOAD_TOO_LARGE", "Upload too large", "文件超过 100MB 限制")
            handle.write(chunk)
    return total


def _delete_raw_evidence(db: Session, material: Material, page_number: int | None = None) -> None:
    query = db.query(EvidenceChunk).filter(
        EvidenceChunk.material_id == material.id,
        or_(EvidenceChunk.source_path.is_(None), ~EvidenceChunk.source_path.like("resume-recognition:%")),
    )
    if page_number is not None:
        query = query.filter(EvidenceChunk.page_number == page_number)
    for row in query.all():
        db.execute(text("DELETE FROM evidence_fts WHERE evidence_id = :id"), {"id": row.id})
        db.delete(row)


def _renumber_raw_evidence(db: Session, material: Material) -> None:
    rows = db.query(EvidenceChunk).filter(
        EvidenceChunk.material_id == material.id,
        or_(EvidenceChunk.source_path.is_(None), ~EvidenceChunk.source_path.like("resume-recognition:%")),
    ).all()
    rows.sort(key=lambda row: (row.page_number is None, row.page_number or 0, row.chunk_order))
    for index, row in enumerate(rows):
        row.chunk_order = index


def ingest_resume(db: Session, material: Material, path: Path, page_number: int | None = None) -> list[dict[str, str | int]]:
    warnings: list[dict[str, str | int]] = []
    try:
        if path.suffix.lower() == ".docx" and page_number is not None:
            warnings.append({"code": "PAGE_RETRY_UNSUPPORTED", "message": "DOCX 暂不支持按页重试，请重试整份解析"})
            page_number = None
        _delete_raw_evidence(db, material, page_number)
        if path.suffix.lower() == ".pdf":
            pages, warnings = _extract_pdf_pages(path, page_number)
            for content, page in pages:
                _add_evidence(db, material, content, page=page)
        elif path.suffix.lower() == ".docx":
            _add_evidence(db, material, _extract_docx(path), source_path=material.filename)
        else:
            raise ValueError("只支持 PDF 或 DOCX 简历")
        _renumber_raw_evidence(db, material)
        raw_count = db.query(EvidenceChunk).filter(
            EvidenceChunk.material_id == material.id,
            or_(EvidenceChunk.source_path.is_(None), ~EvidenceChunk.source_path.like("resume-recognition:%")),
        ).count()
        material.status = "ready" if raw_count else "failed"
    except Exception as exc:
        material.status = "failed"
        material.error_message = str(exc)[:500]
        warnings.append({"code": "RESUME_PARSE_FAILED", "message": material.error_message})
    if warnings:
        material.error_message = "；".join(str(item.get("message", "")) for item in warnings)[:500]
        if material.status == "ready":
            material.status = "partial"
    elif material.status == "ready":
        material.error_message = None
    return warnings


def _zip_member_allowed(name: str, info: zipfile.ZipInfo) -> bool:
    normalized_name = name.replace("\\", "/")
    path = PurePosixPath(normalized_name)
    mode = (info.external_attr >> 16) & 0o170000
    if path.is_absolute() or ".." in path.parts or info.is_dir() or mode == 0o120000:
        return False
    if info.file_size and (info.compress_size == 0 or info.file_size / max(info.compress_size, 1) > 100):
        return False
    suffix = Path(name).suffix.lower()
    return suffix in TEXT_EXTENSIONS or Path(name).name.lower() in {"readme", "dockerfile", "makefile"}


def ingest_project(db: Session, material: Material, path: Path, extraction_dir: Path) -> None:
    try:
        extraction_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path) as archive:
            if len(archive.infolist()) > 10_000:
                raise ValueError("ZIP 文件条目过多")
            if sum(info.file_size for info in archive.infolist()) > 200 * 1024 * 1024:
                raise ValueError("ZIP 解压后文件总量过大")
            for info in archive.infolist():
                normalized_name = info.filename.replace("\\", "/")
                path_parts = PurePosixPath(normalized_name).parts
                mode = (info.external_attr >> 16) & 0o170000
                if PurePosixPath(normalized_name).is_absolute() or ".." in path_parts or mode == 0o120000:
                    raise ValueError(f"ZIP 包含不安全路径：{info.filename}")
                if info.file_size > 5 * 1024 * 1024 or not _zip_member_allowed(info.filename, info):
                    continue
                target = extraction_dir / PurePosixPath(normalized_name)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
                try:
                    content = target.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    content = target.read_text(encoding="utf-8", errors="ignore")
                if content.strip():
                    _add_evidence(db, material, content, source_path=info.filename)
        material.status = "ready" if db.query(EvidenceChunk).filter_by(material_id=material.id).count() else "partial"
    except Exception as exc:
        material.status = "failed"
        material.error_message = str(exc)[:500]
