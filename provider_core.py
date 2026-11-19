"""
PyForge Provider API
Central API registration and authentication core.
"""

import os
import sqlite3
import secrets
import hashlib
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "provider.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_provider():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS registered_clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                project_type TEXT NOT NULL,
                key_hash TEXT NOT NULL,
                active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)


def create_client(name, project_type="bot"):
    if not name or not name.strip():
        raise ValueError("Client name is required")

    api_key = "pf_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    with get_db() as conn:
        conn.execute("""
            INSERT INTO registered_clients
            (name, project_type, key_hash, active, created_at)
            VALUES (?, ?, ?, 1, ?)
        """, (
            name.strip(),
            project_type,
            key_hash,
            datetime.now(timezone.utc).isoformat()
        ))

    return {
        "client": name,
        "api_key": api_key,
        "message": "Client registered successfully. Store this key securely."
    }


def authenticate_client(api_key):
    if not api_key:
        return None

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    with get_db() as conn:
        client = conn.execute("""
            SELECT id, name, project_type, active
            FROM registered_clients
            WHERE key_hash = ?
        """, (key_hash,)).fetchone()

    if client and client["active"] == 1:
        return dict(client)

    return None


def list_clients():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, name, project_type, active, created_at
            FROM registered_clients
            ORDER BY id DESC
        """).fetchall()

    return [dict(row) for row in rows]


initialize_provider()
