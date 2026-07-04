"""Zentrale Konfiguration. Alle Pfade/Secrets über ENV überschreibbar (nie im Repo)."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    db_path: str = os.environ.get("DB_PATH", str(ROOT / "data.db"))
    storage_root: str = os.environ.get("STORAGE_ROOT", str(ROOT / "storage"))
    upload_tmp: str = os.environ.get("UPLOAD_TMP", str(ROOT / "uploads"))
    docs_dir: str = os.environ.get("DOCS_DIR", str(ROOT / "docs"))

    # Auth / Sessions (Meilenstein 2)
    app_secret_key: str = os.environ.get("APP_SECRET_KEY", "")   # base64, 32 Byte
    session_ttl_hours: int = int(os.environ.get("SESSION_TTL_HOURS", "168"))  # 7 Tage
    cookie_name: str = os.environ.get("SESSION_COOKIE", "ldb_session")
    cookie_secure: bool = os.environ.get("COOKIE_SECURE", "0") == "1"  # hinter HTTPS auf 1


settings = Settings()
