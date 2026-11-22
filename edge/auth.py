"""Admin authentication: check a password, hand out and verify short-lived JWTs.

* The admin password is never stored, only its bcrypt hash (slow on purpose,
  so a leaked hash is expensive to brute-force).
* After login the admin gets a signed JWT. The edge can verify it with just
  the secret key: no session table needed. It expires after a few minutes.
"""

import hmac
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

ALGORITHM = "HS256"


class AuthService:
    def __init__(self, username: str, password_hash: str, secret: str, expiry_minutes: int) -> None:
        self._username = username
        self._password_hash = password_hash.encode()
        self._secret = secret
        self.expiry_seconds = expiry_minutes * 60

    def login(self, username: str, password: str) -> str | None:
        """Return a JWT if the credentials are correct, otherwise None."""
        # Always run bcrypt (even for a wrong username) so response time
        # does not reveal whether the username exists.
        password_ok = bcrypt.checkpw(password.encode(), self._password_hash)
        username_ok = hmac.compare_digest(username, self._username)
        if not (password_ok and username_ok):
            return None
        now = datetime.now(timezone.utc)
        claims = {"sub": username, "iat": now, "exp": now + timedelta(seconds=self.expiry_seconds)}
        return jwt.encode(claims, self._secret, algorithm=ALGORITHM)

    def verify(self, token: str) -> bool:
        """True if the token was signed by us and has not expired."""
        try:
            # Pinning the algorithm stops "alg: none" style attacks.
            jwt.decode(token, self._secret, algorithms=[ALGORITHM])
        except jwt.InvalidTokenError:
            return False
        return True
