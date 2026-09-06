#!/bin/sh
set -e

celery -A site_config beat \
  --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
  --schedule="${CELERY_BEAT_SCHEDULE_FILE:-/tmp/celerybeat-schedule}"
