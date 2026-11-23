import sqlite3

from app.domain.ports import UserRepository
from app.domain.user import User
from app.infra.sqlite_repo import SqliteUserRepository


class AccountService:
    def __init__(self, repo: UserRepository):
        self.repo = repo

    def register(self, email: str, name: str) -> User:
        user = User.new(email, name)
        if self.repo.get_by_email(user.email):
            raise ValueError("email already registered")
        return self.repo.add(user)


def make_service(path: str = ":memory:") -> AccountService:
    return AccountService(SqliteUserRepository(sqlite3.connect(path)))
