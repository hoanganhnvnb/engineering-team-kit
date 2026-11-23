import sqlite3
from pathlib import Path

from app.domain.user import User

SCHEMA = (Path(__file__).parent / "schema.sql").read_text()


class SqliteUserRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.executescript(SCHEMA)

    def add(self, user: User) -> User:
        cur = self.conn.execute("INSERT INTO users (email, name) VALUES (?, ?)", (user.email, user.name))
        return User(id=cur.lastrowid, email=user.email, name=user.name)

    def get_by_email(self, email: str) -> User | None:
        row = self.conn.execute("SELECT id, email, name FROM users WHERE email = ?", (email.lower(),)).fetchone()
        return User(*row) if row else None

    def search_by_name(self, term: str, limit: int = 20) -> list[User]:
        rows = self.conn.execute(
            f"SELECT id, email, name FROM users WHERE name LIKE '%{term}%' LIMIT {limit}"
        ).fetchall()
        return [User(*r) for r in rows]
