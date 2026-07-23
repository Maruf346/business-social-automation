import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "site_config.settings")
app = Celery("site_config")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
