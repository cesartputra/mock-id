"""SQLite local / psycopg PostgreSQL adapter. All writes are transactional."""

import os
import re
import sqlite3
from contextlib import contextmanager


class Connection:
    def __init__(self, raw, dialect):
        self.raw, self.dialect = raw, dialect

    def execute(self, query, parameters=()):
        if self.dialect == "postgres":
            query = query.replace("?", "%s")
        return self.raw.execute(query, parameters)

    def executescript(self, script):
        if self.dialect == "postgres":
            script = script.replace(
                "INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY"
            )
            script = re.sub(r"\bREAL\b", "DOUBLE PRECISION", script)
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)


class Database:
    def __init__(self, path):
        self.path = path
        self.url = os.getenv("MOCK_ID_DATABASE_URL")
        self.dialect = "postgres" if self.url else "sqlite"
        if self.url and not self.url.startswith(("postgresql://", "postgres://")):
            raise ValueError("MOCK_ID_DATABASE_URL harus PostgreSQL.")

    @contextmanager
    def connect(self, write=False):
        if self.dialect == "postgres":
            import psycopg
            from psycopg.rows import dict_row

            raw = psycopg.connect(self.url, row_factory=dict_row, connect_timeout=10)
        else:
            raw = sqlite3.connect(self.path, timeout=10)
            raw.row_factory = sqlite3.Row
            raw.execute("PRAGMA foreign_keys=ON")
            raw.execute("PRAGMA secure_delete=ON")
            raw.execute("PRAGMA journal_mode=WAL")
        con = Connection(raw, self.dialect)
        try:
            if write:
                if self.dialect == "sqlite":
                    con.execute("BEGIN IMMEDIATE")
                else:
                    con.execute("SELECT pg_advisory_xact_lock(718294)")
            yield con
            raw.commit()
        except Exception:
            raw.rollback()
            raise
        finally:
            raw.close()

    def compact_legacy(self):
        if self.dialect != "sqlite":
            return
        raw = sqlite3.connect(self.path, timeout=10)
        try:
            raw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            raw.execute("VACUUM")
            raw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            raw.close()
