"""FastAPI-App-Factory. Migrationen + alle Router unter /api, Frontend statisch unter /."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .lib import notifier
from .routers import (
    absences, ai, asuv, auth, backup, branding, calendar, calendar_categories, classes, lehrplan,
    lernbereiche, lessons, materials, noten, notes, planning, push, reflections, school_years,
    schulmanager, search, seating, sequenzplan, settings as settings_router, stoffplan,
    students, stundenplan, sync, todos, users,
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app(db_path: str = None, storage_root: str = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Push-Benachrichtigungen: Minuten-Takt für Erinnerungen + Schulmanager-Abruf.
        # entrypoint.sh startet genau einen uvicorn-Prozess -> kein doppelter Versand.
        scheduler = notifier.Scheduler(app.state.db_path) if settings.scheduler_enabled else None
        if scheduler is not None:
            scheduler.start()
        try:
            yield
        finally:
            if scheduler is not None:
                scheduler.stop()

    app = FastAPI(title="Lehrer-Dashboard API", version="0.9.1", lifespan=lifespan)
    app.state.db_path = db_path or settings.db_path
    app.state.storage_root = storage_root or settings.storage_root

    conn = init_db(app.state.db_path)  # Migrationen + FTS5-Check beim Start
    conn.close()

    @app.get("/api/health", tags=["meta"])
    def health():
        return {"status": "ok", "milestone": 9}

    for module in (auth, settings_router, users, school_years, classes, lernbereiche,
                   lessons, calendar, calendar_categories, materials, reflections, todos,
                   notes, planning, stoffplan, sequenzplan, students, seating, asuv, ai, search,
                   lehrplan, noten,
                   stundenplan, absences, sync, schulmanager, backup, push):
        app.include_router(module.router, prefix="/api")

    # Branding-Routen (Favicon/Manifest, teils Root-Level) VOR dem StaticFiles-Mount.
    app.include_router(branding.router)

    # Frontend zuletzt mounten, damit /api-Routen Vorrang haben.
    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

    return app


app = create_app()
