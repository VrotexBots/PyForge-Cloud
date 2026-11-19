import re
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

ENGINE_NAME = "VaultNex Search Engine"
VERSION = "1.0.0"
DB_PATH = Path(__file__).resolve().parent / "vaultnex_search.db"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class VaultNexSearchEngine:
    def __init__(self, db_path=DB_PATH):
        self.db_path = Path(db_path)
        self.initialise()

    def connect(self):
        connection = sqlite3.connect(str(self.db_path), timeout=15)
        connection.row_factory = sqlite3.Row
        return connection

    def initialise(self):
        with self.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    content TEXT DEFAULT '',
                    source_name TEXT DEFAULT '',
                    country TEXT DEFAULT '',
                    indexed_at TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS search_index
                USING fts5(title, description, content, url)
            """)

    def index_document(self, document):
        url = str(document.get("url", "")).strip()
        title = str(document.get("title", "")).strip()

        if not url.startswith("https://") or not title:
            return False

        description = str(document.get("description", "")).strip()
        content = str(document.get("content", "")).strip()
        source_name = str(document.get("source_name", "")).strip()
        country = str(document.get("country", "")).strip()

        with self.connect() as db:
            existing = db.execute(
                "SELECT id FROM documents WHERE url = ?", (url,)
            ).fetchone()

            if existing:
                doc_id = existing["id"]
                db.execute(
                    """UPDATE documents SET title=?, description=?,
                    content=?, source_name=?, country=?, indexed_at=?
                    WHERE id=?""",
                    (title, description, content, source_name,
                     country, utc_now(), doc_id)
                )
                db.execute("DELETE FROM search_index WHERE rowid=?", (doc_id,))
            else:
                cursor = db.execute(
                    """INSERT INTO documents
                    (url,title,description,content,source_name,country,indexed_at)
                    VALUES (?,?,?,?,?,?,?)""",
                    (url, title, description, content, source_name,
                     country, utc_now())
                )
                doc_id = cursor.lastrowid

            db.execute(
                """INSERT INTO search_index
                (rowid,title,description,content,url)
                VALUES (?,?,?,?,?)""",
                (doc_id, title, description, content, url)
            )

        return True

    def search(self, query, limit=10):
        words = re.findall(r"[A-Za-z0-9]+", str(query).lower())
        if not words:
            return []

        expression = " AND ".join('"' + word + '"' for word in words[:12])

        with self.connect() as db:
            rows = db.execute(
                """SELECT d.title,d.url,d.description,d.content,
                d.source_name,d.country
                FROM search_index f
                JOIN documents d ON d.id=f.rowid
                WHERE search_index MATCH ?
                ORDER BY bm25(search_index)
                LIMIT ?""",
                (expression, max(1, min(int(limit), 50)))
            ).fetchall()

        return [dict(row) for row in rows]

    def health(self):
        with self.connect() as db:
            count = db.execute(
                "SELECT COUNT(*) FROM documents"
            ).fetchone()[0]

        return {
            "engine": ENGINE_NAME,
            "version": VERSION,
            "status": "online",
            "index_documents": count,
            "database": self.db_path.name
        }


engine = VaultNexSearchEngine()


def search_vaultnex(query, country="ZA", max_sources=10):
    results = engine.search(query, max_sources)

    return {
        "provider": "VaultNex",
        "service": ENGINE_NAME,
        "model": "native-retrieval-v1",
        "grounded": bool(results),
        "query": query,
        "country": country,
        "answer": "",
        "results": results,
        "sources": results,
        "source_count": len(results),
        "search_queries": [query]
    }


def health():
    return engine.health()
