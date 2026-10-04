"""异步任务适配层。

本地开发默认使用线程队列，生产可切换到 Celery + Redis；HTTP 层不感知具体队列实现。
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from ..config import settings

try:
    from celery import Celery
except ImportError:  # optional dependency in local MVP
    Celery = None


class TaskQueueUnavailable(RuntimeError):
    pass


def enqueue(run_id: str, local_worker: Callable[[str], None]) -> None:
    if settings.task_queue_backend == "celery":
        if Celery is None:
            raise TaskQueueUnavailable("celery is not installed")
        try:
            celery_app = Celery("ask_resume_agent", broker=settings.redis_url, backend=settings.redis_url)
            celery_app.send_task("app.agent_worker.run", args=[run_id])
            return
        except Exception as exc:
            raise TaskQueueUnavailable(f"redis task queue unavailable: {exc}") from exc
    threading.Thread(target=local_worker, args=(run_id,), daemon=True, name=f"llm-run-{run_id[:8]}").start()
