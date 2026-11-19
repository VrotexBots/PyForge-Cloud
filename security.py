"""PyForge Coding Assistant - Independent Security Layer."""

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "security.sqlite3"

SESSION_HOURS = 12
MAX_FAILURES = 5
LOCKOUT_SECONDS = 900

PASSWORD_PATTERN = re.compile(r"^[A-Za-z0-9]{8}$")


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def initialize():
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS assistant_security (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS login_attempts (
                client_key TEXT PRIMARY KEY,
                failures INTEGER NOT NULL DEFAULT 0,
                locked_until REAL NOT NULL DEFAULT 0
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS assistant_sessions (
                token_hash TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                last_seen REAL NOT NULL
            )
        """)

    try:
        os.chmod(DB_PATH, 0o600)
    except OSError:
        pass


def _hash_password(password, salt):
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=16384,
        r=8,
        p=1,
        dklen=32
    ).hex()


def is_configured():
    initialize()
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM assistant_security WHERE id = 1"
        ).fetchone()
    return row is not None


def configure_password(password):
    initialize()

    if not isinstance(password, str):
        raise ValueError("Password must be text.")

    if not PASSWORD_PATTERN.fullmatch(password):
        raise ValueError(
            "Password must contain exactly 8 letters or numbers."
        )

    salt = secrets.token_bytes(16)
    password_hash = _hash_password(password, salt)

    with connect() as conn:
        existing = conn.execute(
            "SELECT id FROM assistant_security WHERE id = 1"
        ).fetchone()

        if existing:
            raise RuntimeError(
                "Coding Assistant password is already configured."
            )

        conn.execute("""
            INSERT INTO assistant_security
            (id, password_hash, salt, created_at)
            VALUES (1, ?, ?, ?)
        """, (
            password_hash,
            salt.hex(),
            time.time()
        ))

    return True


def login(password, client_key="unknown"):
    initialize()

    client_key = str(client_key)[:128]
    now = time.time()

    with connect() as conn:
        attempt = conn.execute(
            "SELECT * FROM login_attempts WHERE client_key = ?",
            (client_key,)
        ).fetchone()

        if attempt and attempt["locked_until"] > now:
            remaining = int(attempt["locked_until"] - now)
            raise PermissionError(
                f"Too many failed attempts. Try again in {remaining} seconds."
            )

        owner = conn.execute(
            "SELECT password_hash, salt FROM assistant_security WHERE id = 1"
        ).fetchone()

        if owner is None:
            raise RuntimeError(
                "Coding Assistant password has not been configured."
            )

        valid = (
            isinstance(password, str)
            and hmac.compare_digest(
                _hash_password(password, bytes.fromhex(owner["salt"])),
                owner["password_hash"]
            )
        )

        if not valid:
            failures = (
                attempt["failures"] + 1
                if attempt and attempt["locked_until"] <= now
                else 1
            )

            locked_until = (
                now + LOCKOUT_SECONDS
                if failures >= MAX_FAILURES
                else 0
            )

            conn.execute("""
                INSERT INTO login_attempts
                (client_key, failures, locked_until)
                VALUES (?, ?, ?)
                ON CONFLICT(client_key) DO UPDATE SET
                    failures = excluded.failures,
                    locked_until = excluded.locked_until
            """, (client_key, failures, locked_until))

            raise PermissionError("Incorrect Coding Assistant password.")

        conn.execute(
            "DELETE FROM login_attempts WHERE client_key = ?",
            (client_key,)
        )

        token = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires_at = now + SESSION_HOURS * 3600

        conn.execute("""
            INSERT INTO assistant_sessions
            (token_hash, created_at, expires_at, last_seen)
            VALUES (?, ?, ?, ?)
        """, (token_hash, now, expires_at, now))

    return {
        "token": token,
        "expires_at": expires_at
    }


def validate_session(token):
    initialize()

    if not token or not isinstance(token, str):
        return None

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()

    with connect() as conn:
        session = conn.execute(
            "SELECT * FROM assistant_sessions WHERE token_hash = ?",
            (token_hash,)
        ).fetchone()

        if session is None:
            return None

        if session["expires_at"] <= now:
            conn.execute(
                "DELETE FROM assistant_sessions WHERE token_hash = ?",
                (token_hash,)
            )
            return None

        conn.execute(
            "UPDATE assistant_sessions SET last_seen = ? WHERE token_hash = ?",
            (now, token_hash)
        )

        return {
            "authenticated": True,
            "expires_at": session["expires_at"]
        }


def logout(token):
    if not token:
        return

    token_hash = hashlib.sha256(token.encode()).hexdigest()

    with connect() as conn:
        conn.execute(
            "DELETE FROM assistant_sessions WHERE token_hash = ?",
            (token_hash,)
        )


def cleanup_expired_sessions():
    initialize()

    with connect() as conn:
        cursor = conn.execute(
            "DELETE FROM assistant_sessions WHERE expires_at <= ?",
            (time.time(),)
        )
        return cursor.rowcount


initialize()
