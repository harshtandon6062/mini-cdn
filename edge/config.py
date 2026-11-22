"""Edge server settings, read from environment variables (or a local .env file).

All tunables and secrets live here, so nothing secret is written in the code
and every limit can be changed without editing Python.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


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
