import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from pathlib import Path

BASE = Path.home() / "PyForge"
RUNTIME = BASE / "runtime"
DB = RUNTIME / "security.sqlite3"

SESSION_HOURS = 12
MAX_LOGIN_FAILURES = 5
LOCKOUT_SECONDS = 900

RUNTIME.mkdir(parents=True, exist_ok=True)


def _connect():
    conn = sqlite3.connect(str(DB), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _secure_permissions():
    try:
        os.chmod(DB, 0o600)
        if DB.with_name(DB.name + "-wal").exists():
            os.chmod(DB.with_name(DB.name + "-wal"), 0o600)
        if DB.with_name(DB.name + "-shm").exists():
            os.chmod(DB.with_name(DB.name + "-shm"), 0o600)
    except OSError:
        pass


def initialize():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS owner (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                csrf_hash TEXT NOT NULL,
                username TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                last_seen REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS login_attempts (
                client_key TEXT PRIMARY KEY,
                failures INTEGER NOT NULL,
                window_start REAL NOT NULL,
                blocked_until REAL NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT NOT NULL,
                username TEXT,
                client_key TEXT,
                detail TEXT,
                created_at REAL NOT NULL
            )
        """)
    _secure_permissions()


def _password_hash(password, salt):
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=16384,
        r=8,
        p=1,
        dklen=32
    )
    return derived.hex()


def owner_exists():
    initialize()
    with _connect() as conn:
        return conn.execute(
            "SELECT 1 FROM owner WHERE id=1"
        ).fetchone() is not None


def create_owner(password, username="owner"):
    initialize()

    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("Password must contain at least 8 characters.")

    if not username or len(username) > 64:
        raise ValueError("Invalid username.")

    salt = secrets.token_bytes(16)
    password_hash = _password_hash(password, salt)

    with _connect() as conn:
        existing = conn.execute(
            "SELECT 1 FROM owner WHERE id=1"
        ).fetchone()

        if existing:
            raise RuntimeError("Owner account already exists.")

        conn.execute(
            """INSERT INTO owner
               (id, username, password_hash, salt, created_at)
               VALUES (1, ?, ?, ?, ?)""",
            (username, password_hash, salt.hex(), time.time())
        )

    _secure_permissions()
    audit("owner_account_created", username, "local", "Initial owner setup")


def _record_failure(client_key):
    now = time.time()

    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM login_attempts WHERE client_key=?",
            (client_key,)
        ).fetchone()

        if row is None or now - row["window_start"] > LOCKOUT_SECONDS:
            failures = 1
            window_start = now
        else:
            failures = row["failures"] + 1
            window_start = row["window_start"]

        blocked_until = (
            now + LOCKOUT_SECONDS
            if failures >= MAX_LOGIN_FAILURES
            else 0
        )

        conn.execute("""
            INSERT OR REPLACE INTO login_attempts
            (client_key, failures, window_start, blocked_until)
            VALUES (?, ?, ?, ?)
        """, (client_key, failures, window_start, blocked_until))


def _is_blocked(client_key):
    now = time.time()

    with _connect() as conn:
        row = conn.execute(
            "SELECT blocked_until FROM login_attempts WHERE client_key=?",
            (client_key,)
        ).fetchone()

    return bool(row and row["blocked_until"] > now)


def _clear_failures(client_key):
    with _connect() as conn:
        conn.execute(
            "DELETE FROM login_attempts WHERE client_key=?",
            (client_key,)
        )


def audit(event, username=None, client_key=None, detail=None):
    initialize_if_needed = DB.exists()

    if not initialize_if_needed:
        initialize()

    with _connect() as conn:
        conn.execute("""
            INSERT INTO audit_events
            (event, username, client_key, detail, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            str(event)[:100],
            username,
            str(client_key or "unknown")[:100],
            str(detail or "")[:500],
            time.time()
        ))

    _secure_permissions()


def login(username, password, client_key="local"):
    initialize()
    client_key = str(client_key or "unknown")[:100]

    if _is_blocked(client_key):
        audit("login_blocked", username, client_key)
        raise PermissionError("Too many failed attempts. Try again later.")

    with _connect() as conn:
        owner = conn.execute(
            "SELECT * FROM owner WHERE id=1"
        ).fetchone()

    if owner is None:
        raise RuntimeError("Owner account has not been configured.")

    valid = (
        isinstance(username, str)
        and isinstance(password, str)
        and hmac.compare_digest(username, owner["username"])
        and hmac.compare_digest(
            _password_hash(password, bytes.fromhex(owner["salt"])),
            owner["password_hash"]
        )
    )

    if not valid:
        _record_failure(client_key)
        audit("login_failed", username, client_key)
        raise PermissionError("Incorrect username or password.")

    _clear_failures(client_key)

    now = time.time()
    token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    csrf_hash = hashlib.sha256(csrf_token.encode()).hexdigest()

    with _connect() as conn:
        conn.execute("""
            INSERT INTO sessions
            (token_hash, csrf_hash, username, created_at, expires_at, last_seen)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            token_hash,
            csrf_hash,
            owner["username"],
            now,
            now + SESSION_HOURS * 3600,
            now
        ))

    audit("login_success", owner["username"], client_key)

    return {
        "token": token,
        "csrf_token": csrf_token,
        "username": owner["username"],
        "expires_at": now + SESSION_HOURS * 3600
    }


def validate_session(token, csrf_token=None, require_csrf=False):
    initialize()

    if not token or not isinstance(token, str):
        return None

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()

    with _connect() as conn:
        session = conn.execute(
            "SELECT * FROM sessions WHERE token_hash=?",
            (token_hash,)
        ).fetchone()

        if session is None:
            return None

        if session["expires_at"] <= now:
            conn.execute(
                "DELETE FROM sessions WHERE token_hash=?",
                (token_hash,)
            )
            return None

        if require_csrf:
            if not csrf_token or not hmac.compare_digest(
                hashlib.sha256(csrf_token.encode()).hexdigest(),
                session["csrf_hash"]
            ):
                return None

        conn.execute(
            "UPDATE sessions SET last_seen=? WHERE token_hash=?",
            (now, token_hash)
        )

    return {
        "username": session["username"],
        "expires_at": session["expires_at"]
    }


def logout(token, client_key="unknown"):
    if not token:
        return

    token_hash = hashlib.sha256(token.encode()).hexdigest()

    with _connect() as conn:
        session = conn.execute(
            "SELECT username FROM sessions WHERE token_hash=?",
            (token_hash,)
        ).fetchone()

        conn.execute(
            "DELETE FROM sessions WHERE token_hash=?",
            (token_hash,)
        )

    if session:
        audit("logout", session["username"], client_key)


def get_audit_events(limit=100):
    initialize()
    limit = max(1, min(int(limit), 500))

    with _connect() as conn:
        rows = conn.execute(
            """SELECT event, username, client_key, detail, created_at
               FROM audit_events ORDER BY id DESC LIMIT ?""",
            (limit,)
        ).fetchall()

    return [dict(row) for row in rows]


def cleanup_expired_sessions():
    initialize()

    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM sessions WHERE expires_at <= ?",
            (time.time(),)
        )
        return cursor.rowcount


initialize()
