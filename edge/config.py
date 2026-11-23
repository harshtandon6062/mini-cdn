"""Edge server settings, read from environment variables (or a local .env file).

All tunables and secrets live here, so nothing secret is written in the code
and every limit can be changed without editing Python.
"""

from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_POLICY_FILE = Path(__file__).resolve().parent.parent / "policy.json"


class UserAccount(BaseModel):
    role: str
    password_hash: str  # bcrypt hash, see scripts/hash_password.py


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    origin_url: str = "http://127.0.0.1:8001"
    origin_timeout_seconds: float = 5.0

    cache_max_entries: int = 100

    rate_limit_capacity: int = 20  # burst size: requests allowed at once
    rate_limit_refill_per_second: float = 5.0  # sustained requests per second

    # No defaults on purpose: the edge refuses to start without real secrets.
    jwt_secret: str
    jwt_expiry_minutes: int = 15
    admin_username: str = "admin"
    admin_password_hash: str  # bcrypt hash, see scripts/hash_password.py

    # Zero trust: every proxied request needs a valid user JWT + a policy match.
    zero_trust_enabled: bool = True
    policy_file: str = str(DEFAULT_POLICY_FILE)
    # Extra users as JSON, e.g. {"alice": {"role": "engineer", "password_hash": "..."}}
    users: dict[str, UserAccount] = {}

    def all_users(self) -> dict[str, UserAccount]:
        """The configured users plus the admin account (role "admin")."""
        admin = UserAccount(role="admin", password_hash=self.admin_password_hash)
        return {**self.users, self.admin_username: admin}
