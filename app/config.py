from dataclasses import dataclass
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Android Admin")
    app_env: str = os.getenv("APP_ENV", "production")
    admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "admin123")
    session_secret: str = os.getenv("SESSION_SECRET", "change-this-secret")
    db_path: str = os.getenv("DB_PATH", str(BASE_DIR / "database" / "platform.db"))
    demo_mode: bool = _bool("DEMO_MODE", True)
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "80"))


settings = Settings()
