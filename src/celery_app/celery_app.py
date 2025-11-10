# src/celery_app/celery_app.py
from celery import Celery
import os
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "fastcite_tasks",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["celery_app.tasks"],  # 👈 THIS LINE IS CRUCIAL
)

celery_app.conf.update(
    task_default_queue="default",
    broker_connection_retry_on_startup=True,
)

@celery_app.task(name="celery_app.health_check")
def health_check():
    return "✅ Celery is alive!"
