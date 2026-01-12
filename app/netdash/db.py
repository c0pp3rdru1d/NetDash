from __future__ import annotations

import os
import sqlite3
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Iterable


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS hosts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ping_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    host TEXT NOT NULL,
    ok INTEGER NOT NULL,
    rtt_ms REAL,
    ts TEXT NOT NULL,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_ping_results_host_ts ON ping_results(host, ts);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


async def init_db(db_path: Path) -> None:
    def _init() -> None:
        conn = _connect(db_path)
        try:
            conn.executescript(SCHEMA)
        finally:
            conn.close()

    await asyncio.to_thread(_init)


async def add_host(db_path: Path, name: str) -> None:
    name = name.strip()
    if not name:
        raise ValueError("Host name cannot be empty.")

    def _add() -> None:
        conn = _connect(db_path)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO hosts(name, created_at) VALUES(?, ?)",
                (name, datetime.utcnow().isoformat()),
            )
        finally:
            conn.close()

    await asyncio.to_thread(_add)


async def list_hosts(db_path: Path) -> list[str]:
    def _list() -> list[str]:
        conn = _connect(db_path)
        try:
            cur = conn.execute("SELECT name FROM hosts ORDER BY name ASC")
            return [row[0] for row in cur.fetchall()]
        finally:
            conn.close()

    return await asyncio.to_thread(_list)


async def write_ping(db_path: Path, host: str, ok: bool, rtt_ms: float | None, error: str | None) -> None:
    def _write() -> None:
        conn = _connect(db_path)
        try:
            conn.execute(
                "INSERT INTO ping_results(host, ok, rtt_ms, ts, error) VALUES(?, ?, ?, ?, ?)",
                (host, 1 if ok else 0, rtt_ms, datetime.utcnow().isoformat(), error),
            )
        finally:
            conn.close()

    await asyncio.to_thread(_write)


async def latest_status(db_path: Path, limit: int = 50) -> list[tuple[str, int, float | None, str, str | None]]:
    def _q():
        conn = _connect(db_path)
        try:
            cur = conn.execute(
                """
                SELECT host, ok, rtt_ms, ts, error
                FROM ping_results
                ORDER BY ts DESC
                LIMIT ?
                """,
                (limit,),
            )
            return cur.fetchall()
        finally:
            conn.close()

    return await asyncio.to_thread(_q)

