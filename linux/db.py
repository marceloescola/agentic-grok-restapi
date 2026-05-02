from __future__ import annotations

import os
import sqlite3
from typing import List, Optional

from session_model import MessageInfo, SessionInfo

DB_DIR = os.path.expanduser("~/.grok-bridge")
DB_PATH = os.path.join(DB_DIR, "sessions.db")


class SessionDB:
    def __init__(self, db_path: str = DB_PATH) -> None:
        self._db_path: str = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def init_db(self) -> None:
        os.makedirs(DB_DIR, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.commit()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.init_db()
        assert self._conn is not None
        return self._conn

    def add_session(self, name: str, url: str) -> SessionInfo:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO sessions (name, url) VALUES (?, ?)",
            (name, url),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT id, name, url, created_at, updated_at FROM sessions WHERE url = ?",
            (url,),
        ).fetchone()
        assert row is not None
        return SessionInfo(
            id=row["id"],
            name=row["name"],
            url=row["url"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def update_session_name(self, session_id: int, name: str) -> None:
        self.conn.execute(
            "UPDATE sessions SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (name, session_id),
        )
        self.conn.commit()

    def list_sessions(self) -> List[SessionInfo]:
        rows = self.conn.execute(
            "SELECT id, name, url, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
        return [
            SessionInfo(
                id=r["id"],
                name=r["name"],
                url=r["url"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    def get_session(self, session_id: int) -> Optional[SessionInfo]:
        row = self.conn.execute(
            "SELECT id, name, url, created_at, updated_at FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return SessionInfo(
            id=row["id"],
            name=row["name"],
            url=row["url"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def delete_session(self, session_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def save_messages(
        self, session_id: int, messages: List[MessageInfo]
    ) -> None:
        self.conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        for msg in messages:
            self.conn.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, msg.role, msg.content),
            )
        self.conn.commit()

    def get_messages(self, session_id: int) -> List[MessageInfo]:
        rows = self.conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        return [MessageInfo(role=r["role"], content=r["content"]) for r in rows]

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
