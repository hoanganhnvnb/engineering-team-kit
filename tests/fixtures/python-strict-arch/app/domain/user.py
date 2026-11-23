from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    id: int | None
    email: str
    name: str

    @staticmethod
    def new(email: str, name: str) -> "User":
        email = email.strip().lower()
        if "@" not in email:
            raise ValueError("invalid email")
        return User(id=None, email=email, name=name.strip())
