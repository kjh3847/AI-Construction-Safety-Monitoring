"""Central PostgreSQL account store, independent of local video storage."""
import os
import psycopg
from psycopg.rows import dict_row


def connect():
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise RuntimeError('DATABASE_URL is required; configure PostgreSQL or RDS.')
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=5)


def init_identity():
    with connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS accounts (
            employee_id TEXT PRIMARY KEY, email TEXT NOT NULL,
            password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('system','admin')),
            status TEXT NOT NULL CHECK(status IN ('pending','active','disabled')),
            must_change_password BOOLEAN NOT NULL DEFAULT TRUE,
            failed_attempts INTEGER NOT NULL DEFAULT 0, locked_until TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
        db.execute('''CREATE TABLE IF NOT EXISTS account_sessions (
            token_hash TEXT PRIMARY KEY, employee_id TEXT NOT NULL REFERENCES accounts(employee_id),
            expires_at TIMESTAMPTZ NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS account_audit (
            id BIGSERIAL PRIMARY KEY, actor TEXT NOT NULL, employee_id TEXT NOT NULL,
            action TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
