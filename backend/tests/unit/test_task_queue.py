import pytest

from app.infrastructure.task_queue import TaskQueueUnavailable, enqueue


def test_celery_queue_failure_is_reported_as_infrastructure_error(monkeypatch):
    class BrokenCelery:
        def __init__(self, *args, **kwargs):
            pass

        def send_task(self, *args, **kwargs):
            raise ConnectionError("redis down")

    monkeypatch.setattr("app.infrastructure.task_queue.Celery", BrokenCelery, raising=False)
    monkeypatch.setattr("app.infrastructure.task_queue.settings.task_queue_backend", "celery")
    with pytest.raises(TaskQueueUnavailable):
        enqueue("run-1", lambda _: None)
