import os

bind = "0.0.0.0:8000"
# Parallel deliveries are handled by processes x threads. Each worker has its own DB
# pool (DB_POOL_SIZE + DB_MAX_OVERFLOW), which must stay under Postgres max_connections.
workers = int(os.environ.get("WEB_CONCURRENCY", "4"))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", "8"))
timeout = 30
graceful_timeout = 20
keepalive = 5
accesslog = "-"
