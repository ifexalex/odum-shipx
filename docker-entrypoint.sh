#!/usr/bin/env sh
# Entrypoint for the ShipX backend container. The first argument selects the
# workload so one image serves the API, the queue workers, and the cron jobs.
#
#   api                      → gunicorn HTTP API (default)
#   worker --queue <key>     → Service Bus consumer for one queue
#   job --job <name>         → run one scheduled job once, then exit
#   migrate                  → apply Alembic migrations, then exit
#   <anything else>          → exec verbatim (debugging)
set -e

cmd="${1:-api}"

case "$cmd" in
  api)
    # Processes, NOT threads: shared/db.py holds a per-process connection
    # singleton that is not thread-safe, so each gunicorn worker must be its own
    # process with its own connection — the container analogue of a Lambda
    # execution environment. Keep --threads at 1.
    exec gunicorn \
      --bind "0.0.0.0:${PORT:-8080}" \
      --workers "${GUNICORN_WORKERS:-2}" \
      --threads 1 \
      --timeout "${GUNICORN_TIMEOUT:-60}" \
      --access-logfile - \
      --error-logfile - \
      services.http_app.app:app
    ;;
  worker)
    shift
    exec python -m services.queue_worker.worker "$@"
    ;;
  job)
    shift
    exec python -m services.scheduled.run "$@"
    ;;
  migrate)
    exec python scripts/migrate.py
    ;;
  *)
    exec "$@"
    ;;
esac
