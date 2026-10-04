"""Celery 入口；本地默认队列仍使用 task_queue 的线程适配器。"""

from celery import Celery

from .config import settings
from .db import SessionLocal
from .service.agent_follow_up_service import AgentWorker

celery_app = Celery("ask_resume_agent", broker=settings.redis_url, backend=settings.redis_url)


@celery_app.task(name="app.agent_worker.run")
def run(run_id: str) -> None:
    db = SessionLocal()
    try:
        AgentWorker(db).run(run_id)
    finally:
        db.close()
