"""SQLite-Verbindung, PRAGMAs, FTS5-Check und Migrationsrunner.

Eine Verbindung pro Request (siehe deps.get_db): mit WAL erlaubt das nebenläufige
Leser + genau einen Schreiber und vermeidet Thread-Sharing-Probleme von sqlite3.
"""
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def connect(db_path: str) -> sqlite3.Connection:
    # check_same_thread=False: FastAPI löst sync-Dependencies im Threadpool auf,
    # sodass eine per-Request-Connection über Threads hinweg (aber sequenziell,
    # nie nebenläufig) genutzt wird. busy_timeout entschärft WAL-Sperren.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    if db_path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def assert_fts5(conn: sqlite3.Connection) -> None:
    """Früh und laut scheitern, falls das System-SQLite kein FTS5 mitbringt."""
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(x)")
        conn.execute("DROP TABLE IF EXISTS _fts5_probe")
    except sqlite3.OperationalError as exc:  # pragma: no cover - umgebungsabhängig
        raise RuntimeError(
            "SQLite FTS5 ist nicht verfügbar. Für das Docker-Deployment ein Python-Image "
            "mit FTS5-fähigem SQLite verwenden oder 'pysqlite3-binary' einbinden."
        ) from exc


def run_migrations(conn: sqlite3.Connection) -> list:
    """Wendet noch nicht angewandte *.sql aus migrations/ an. Idempotent."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "filename TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    applied = {r[0] for r in conn.execute("SELECT filename FROM schema_migrations")}
    newly = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in applied:
            continue
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migrations(filename) VALUES (?)", (path.name,))
        conn.commit()
        newly.append(path.name)
    return newly


def init_db(db_path: str) -> sqlite3.Connection:
    conn = connect(db_path)
    assert_fts5(conn)
    run_migrations(conn)
    return conn
