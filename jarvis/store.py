"""Long-term memory: facts about the user plus a log of every conversation, in one SQLite file."""
import sqlite3
import threading
from datetime import datetime

from .config import DATA_DIR


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY, text TEXT NOT NULL, created TEXT);
                CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, role TEXT, content TEXT, ts TEXT);
            """)

    def _q(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur.fetchall()

    def add_fact(self, text: str) -> int:
        with self.lock:
            cur = self.db.execute("INSERT INTO facts (text, created) VALUES (?, ?)",
                                  (text.strip(), datetime.now().isoformat(timespec="seconds")))
            self.db.commit()
            return cur.lastrowid

    def facts(self, limit: int = 40) -> list[tuple[int, str]]:
        return self._q("SELECT id, text FROM facts ORDER BY id DESC LIMIT ?", (limit,))[::-1]

    def search_facts(self, query: str) -> list[tuple[int, str]]:
        words = [w for w in query.lower().split() if len(w) > 2] or [query.lower()]
        clause = " OR ".join("lower(text) LIKE ?" for _ in words)
        return self._q(f"SELECT id, text FROM facts WHERE {clause} ORDER BY id", [f"%{w}%" for w in words])

    def delete_fact(self, fact_id: int) -> bool:
        with self.lock:
            cur = self.db.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
            self.db.commit()
            return cur.rowcount > 0

    def log(self, role: str, content: str):
        self._q("INSERT INTO messages (role, content, ts) VALUES (?, ?, ?)",
                (role, content, datetime.now().isoformat(timespec="seconds")))

    def recent(self, n: int = 10) -> list[dict]:
        rows = self._q("SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (n,))
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    def search_log(self, query: str, limit: int = 8) -> list[tuple[str, str, str]]:
        return self._q("SELECT ts, role, content FROM messages WHERE lower(content) LIKE ? "
                       "ORDER BY id DESC LIMIT ?", (f"%{query.lower()}%", limit))


store = Store(DATA_DIR / "jarvis.db")
