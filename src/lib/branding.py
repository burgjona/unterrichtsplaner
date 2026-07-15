"""M12/U10: Branding-Uploads (Profilbild + Logo) – Ablage im .branding-Unterbaum.

Bilder werden analog zum Material-Upload (routers/materials.py) gestreamt (Größenlimit),
atomar via Temp-Datei + os.replace geschrieben und über denselben Root-Guard abgesichert.
Keine DB-I/O hier – rein Datei/Validierung, damit testbar und wiederverwendbar
(routers/users.py Avatar, routers/settings.py Logo, routers/branding.py Favicon/Manifest).
"""
import os
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

MAX_BRANDING_BYTES = 5 * 1024 * 1024  # 5 MB
BRANDING_DIRNAME = ".branding"

# Erlaubte Bild-Endungen → Media-Type fürs Ausliefern.
_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".bmp": "image/bmp",
}


def ensure_under_root(path: str, storage_root: str) -> str:
    """Wie materials._ensure_under_root: Zielpfad muss im Storage-Baum liegen."""
    resolved = os.path.realpath(path)
    root = os.path.realpath(storage_root)
    if resolved != root and not resolved.startswith(root + os.sep):
        raise HTTPException(status_code=400,
                            detail="Pfad muss unterhalb des Storage-Verzeichnisses liegen.")
    return resolved


def _ext_for(file: UploadFile) -> str:
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext == ".jpe":
        ext = ".jpeg"
    if ext not in _IMAGE_TYPES:
        raise HTTPException(status_code=415,
                            detail="Nur Bilddateien erlaubt (png, jpg, gif, webp, svg, ico, bmp).")
    return ext


def media_type_for(path: str) -> str:
    return _IMAGE_TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


def resolve_relpath(relpath: str, storage_root: str) -> str:
    """Relativen (oder Alt-Bestand: absoluten) Pfad zu gesichertem Absolutpfad auflösen."""
    path = relpath if os.path.isabs(relpath) else os.path.join(storage_root, relpath)
    return ensure_under_root(path, storage_root)


async def save_image_upload(file: UploadFile, basename: str, storage_root: str) -> str:
    """Validiert (image/*, erlaubte Endung, ≤ 5 MB), speichert atomar unter
    ``{storage_root}/.branding/{basename}.<ext>`` und gibt den *relativen* Pfad
    (posix, z. B. ".branding/logo.png") zurück. Ältere Datei gleichen Basenamens
    (andere Endung) wird ersetzt, sodass je Basename nur eine Datei existiert."""
    if not (file.content_type or "").lower().startswith("image/"):
        raise HTTPException(status_code=415, detail="Nur Bilddateien (image/*) erlaubt.")
    ext = _ext_for(file)
    brand_dir = Path(storage_root) / BRANDING_DIRNAME
    brand_dir.mkdir(parents=True, exist_ok=True)
    for old in brand_dir.glob(basename + ".*"):
        try:
            old.unlink()
        except OSError:  # pragma: no cover
            pass
    target = brand_dir / f"{basename}{ext}"
    ensure_under_root(str(target), storage_root)
    tmp = brand_dir / f"{uuid.uuid4().hex}.part"
    size = 0
    try:
        with open(tmp, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BRANDING_BYTES:
                    raise HTTPException(status_code=413, detail="Datei zu groß (max. 5 MB).")
                out.write(chunk)
        os.replace(tmp, target)
    except HTTPException:
        if tmp.exists():
            tmp.unlink()
        raise
    except Exception as exc:  # pragma: no cover
        if tmp.exists():
            tmp.unlink()
        raise HTTPException(status_code=500, detail=f"Upload fehlgeschlagen: {exc}")
    return f"{BRANDING_DIRNAME}/{basename}{ext}"
