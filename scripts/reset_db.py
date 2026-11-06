#!/usr/bin/env python3
"""Drop and recreate the logistics database.

Uses the same DATABASE_* env vars as migrate.py so it always targets
the correct postgres instance regardless of local vs Docker setup.
"""

import os

import psycopg2

host = os.environ["DATABASE_HOST"]
port = os.environ.get("DATABASE_PORT", "5432")
user = os.environ["DATABASE_USER"]
password = os.environ["DATABASE_PASSWORD"]
dbname = os.environ["DATABASE_NAME"]

conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname="postgres")
conn.autocommit = True
cur = conn.cursor()

# Terminate any active connections so DROP DATABASE succeeds
cur.execute(
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
    (dbname,),
)
cur.execute(f"DROP DATABASE IF EXISTS {dbname}")
cur.execute(f"CREATE DATABASE {dbname}")
print(f"Database '{dbname}' reset complete.")
