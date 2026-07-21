"""FastAPI-App-Factory. Migrationen + alle Router unter /api, Frontend statisch unter /."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .routers import (
    ai, asuv, auth, branding, calendar, calendar_categories, classes, lernbereiche,
    lessons, materials, notes, planning, reflections, school_years, search, seating,
    settings as settings_router, stoffplan, students, stundenplan, todos, users,
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app(db_path: str = None, storage_root: str = None) -> FastAPI:
    app = FastAPI(title="Lehrer-Dashboard API", version="0.9.1")
    app.state.db_path = db_path or settings.db_path
    app.state.storage_root = storage_root or settings.storage_root

    conn = init_db(app.state.db_path)  # Migrationen + FTS5-Check beim Start
    conn.close()

    @app.get("/api/health", tags=["meta"])
    def health():
        return {"status": "ok", "milestone": 9}

    for module in (auth, settings_router, users, school_years, classes, lernbereiche,
                   lessons, calendar, calendar_categories, materials, reflections, todos,
                   notes, planning, stoffplan, students, seating, asuv, ai, search,
                   stundenplan):
        app.include_router(module.router, prefix="/api")

    # Branding-Routen (Favicon/Manifest, teils Root-Level) VOR dem StaticFiles-Mount.
    app.include_router(branding.router)

    # Frontend zuletzt mounten, damit /api-Routen Vorrang haben.
    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

    return app


app = create_app()
