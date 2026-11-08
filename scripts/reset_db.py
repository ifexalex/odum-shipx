#!/usr/bin/env python3
"""Drop and recreate the logistics database.

Uses the same DATABASE_* env vars as migrate.py so it always targets the correct
postgres instance regardless of local vs Docker setup — and the same
owner-not-application credential, since DROP/CREATE DATABASE needs privileges
`logistics_app` does not have. See shared/db_credentials.py.
"""

import psycopg2

from shared.db_credentials import admin_db_params

params = admin_db_params()
dbname = params["dbname"]

conn = psycopg2.connect(**{**params, "dbname": "postgres"})
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
