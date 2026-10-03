"""文档与项目材料的基础设施适配器。

保留旧模块导出，避免影响已有调用方；业务服务只依赖本层的适配器入口。
"""

from ..services.ingestion import ingest_project, ingest_resume, save_upload

__all__ = ["ingest_project", "ingest_resume", "save_upload"]
