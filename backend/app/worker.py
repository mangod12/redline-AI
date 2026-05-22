"""Celery application for Redline AI background tasks.

Start worker:
    celery -A app.worker.celery_app worker --loglevel=info
"""

from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "redline_ai",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # Visibility timeout — tasks not acked within this window get redelivered
    broker_transport_options={"visibility_timeout": 300},
    # Result expiry — don't keep results forever
    result_expires=3600,
    # Task time limits
    task_soft_time_limit=60,
    task_time_limit=120,
    # Worker memory limit — restart if exceeds 256MB
    worker_max_memory_per_child=256_000,
)
