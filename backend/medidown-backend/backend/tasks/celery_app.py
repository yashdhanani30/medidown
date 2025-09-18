from celery import Celery
import os

# Celery configuration (for background tasks if needed)
celery_app = Celery(
    'tasks',
    broker=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
    backend=os.getenv('REDIS_URL', 'redis://localhost:6379/0')
)

celery_app.conf.update(
    result_expires=3600,
)