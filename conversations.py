"""PyForge Coding Assistant - Persistent Conversation Storage."""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "conversations.sqlite3"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize():
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                project_name TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id)
                    REFERENCES conversations(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS project_context (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                context_key TEXT NOT NULL,
                context_value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(project_name, context_key)
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_conversation
            ON messages(conversation_id, id)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_updated
            ON conversations(updated_at)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_project_context_name
            ON project_context(project_name)
        """)

    try:
        DB_PATH.chmod(0o600)
    except OSError:
        pass


def create_conversation(title="New conversation", project_name=None):
    conversation_id = str(uuid.uuid4())
    now = utc_now()

    with connect() as conn:
        conn.execute("""
            INSERT INTO conversations
            (id, title, project_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            conversation_id,
            title,
            project_name,
            now,
            now
        ))

    return conversation_id


def list_conversations(include_archived=False):
    query = """
        SELECT id, title, project_name, created_at, updated_at, archived
        FROM conversations
    """

    if not include_archived:
        query += " WHERE archived = 0"

    query += " ORDER BY updated_at DESC"

    with connect() as conn:
        rows = conn.execute(query).fetchall()

    return [dict(row) for row in rows]


def get_conversation(conversation_id):
    with connect() as conn:
        row = conn.execute("""
            SELECT *
            FROM conversations
            WHERE id = ?
        """, (conversation_id,)).fetchone()

    return dict(row) if row else None


def add_message(conversation_id, role, content):
    if role not in ("user", "assistant", "system", "tool"):
        raise ValueError("Unsupported message role.")

    if not isinstance(content, str):
        raise ValueError("Message content must be text.")

    now = utc_now()

    with connect() as conn:
        conversation = conn.execute(
            "SELECT id FROM conversations WHERE id = ?",
            (conversation_id,)
        ).fetchone()

        if conversation is None:
            raise ValueError("Conversation does not exist.")

        cursor = conn.execute("""
            INSERT INTO messages
            (conversation_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
        """, (conversation_id, role, content, now))

        conn.execute("""
            UPDATE conversations
            SET updated_at = ?
            WHERE id = ?
        """, (now, conversation_id))

        return cursor.lastrowid


def get_messages(conversation_id, limit=None):
    with connect() as conn:
        if limit is None:
            rows = conn.execute("""
                SELECT id, role, content, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY id ASC
            """, (conversation_id,)).fetchall()
        else:
            if not isinstance(limit, int) or limit < 1:
                raise ValueError("Limit must be a positive integer.")

            rows = conn.execute("""
                SELECT id, role, content, created_at
                FROM (
                    SELECT id, role, content, created_at
                    FROM messages
                    WHERE conversation_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                )
                ORDER BY id ASC
            """, (conversation_id, limit)).fetchall()

    return [dict(row) for row in rows]


def rename_conversation(conversation_id, title):
    if not isinstance(title, str) or not title.strip():
        raise ValueError("A conversation title is required.")

    with connect() as conn:
        cursor = conn.execute("""
            UPDATE conversations
            SET title = ?, updated_at = ?
            WHERE id = ?
        """, (title.strip(), utc_now(), conversation_id))

    return cursor.rowcount == 1


def archive_conversation(conversation_id):
    with connect() as conn:
        cursor = conn.execute("""
            UPDATE conversations
            SET archived = 1, updated_at = ?
            WHERE id = ?
        """, (utc_now(), conversation_id))

    return cursor.rowcount == 1


def save_project_context(project_name, context_key, context_value):
    if not project_name or not context_key:
        raise ValueError("Project name and context key are required.")

    if not isinstance(context_value, str):
        raise ValueError("Context value must be text.")

    now = utc_now()

    with connect() as conn:
        conn.execute("""
            INSERT INTO project_context
            (project_name, context_key, context_value, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(project_name, context_key)
            DO UPDATE SET
                context_value = excluded.context_value,
                updated_at = excluded.updated_at
        """, (
            project_name,
            context_key,
            context_value,
            now,
            now
        ))


def get_project_context(project_name):
    with connect() as conn:
        rows = conn.execute("""
            SELECT context_key, context_value, updated_at
            FROM project_context
            WHERE project_name = ?
            ORDER BY context_key
        """, (project_name,)).fetchall()

    return [dict(row) for row in rows]


initialize()
