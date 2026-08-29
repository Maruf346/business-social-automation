#!/bin/sh
set -e

exec celery -A site_config worker \
  --loglevel "${CELERY_LOG_LEVEL:-INFO}" \
  --concurrency "${CELERY_WORKER_CONCURRENCY:-2}"
