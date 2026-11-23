"""User authentication: check a password, hand out and verify short-lived JWTs.

* Passwords are never stored, only bcrypt hashes (slow on purpose, so a
  leaked hash is expensive to brute-force).
* After login a user gets a signed JWT with two claims: "sub" (who) and
  "role" (what they are). The edge verifies it with just the secret key on
  every request: no session table needed. It expires after a few minutes.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from edge.config import UserAccount

ALGORITHM = "HS256"


@dataclass(frozen=True)
class Identity:
    """Who is making the request, taken from a verified token."""

    sub: str
    role: str


class AuthService:
    def __init__(self, users: dict[str, UserAccount], secret: str, expiry_minutes: int) -> None:
        self._users = users
        self._secret = secret
        self.expiry_seconds = expiry_minutes * 60
        # Used for unknown usernames so a wrong username takes as long as a wrong password.
        self._dummy_hash = next(iter(users.values())).password_hash.encode()

    def login(self, username: str, password: str) -> str | None:
        """Return a JWT if the credentials are correct, otherwise None."""
        account = self._users.get(username)
        password_hash = account.password_hash.encode() if account else self._dummy_hash
        password_ok = bcrypt.checkpw(password.encode(), password_hash)
        if account is None or not password_ok:
            return None
        now = datetime.now(timezone.utc)
        claims = {
            "sub": username,
            "role": account.role,
            "iat": now,
            "exp": now + timedelta(seconds=self.expiry_seconds),
        }
        return jwt.encode(claims, self._secret, algorithm=ALGORITHM)

    def role_of(self, username: str) -> str:
        """The role of a known user."""
        return self._users[username].role

    def verify(self, token: str) -> Identity | None:
        """Return who the token belongs to if it is ours and not expired, else None."""
        try:
            # Pinning the algorithm stops "alg: none" style attacks.
            claims = jwt.decode(
                token, self._secret, algorithms=[ALGORITHM], options={"require": ["exp", "sub"]}
            )
        except jwt.InvalidTokenError:
            return None
        return Identity(sub=claims["sub"], role=claims.get("role", ""))
