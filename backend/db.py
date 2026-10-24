"""Shared Postgres connection — imported by graph.py and handoff.py."""
from __future__ import annotations

import os

from dotenv import load_dotenv
from psycopg import Connection

load_dotenv()

_DB_URI = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5433/agentdb",
)

# Application connection — used for ticket inserts, conversation_titles, etc.
conn: Connection = Connection.connect(_DB_URI, autocommit=True)

# Dedicated connection for PostgresSaver — it uses pipeline mode internally and
# must not share a connection with application DML operations.
checkpointer_conn: Connection = Connection.connect(_DB_URI, autocommit=True)


def setup_schema() -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversation_titles (
            thread_id   TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            created_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            ticket_id   TEXT PRIMARY KEY,
            thread_id   TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'open',
            summary     TEXT,
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            resolved_at TIMESTAMPTZ
        )
    """)
