"""CRUD Material-Metadaten + Mehrfachverknüpfung (nutzer-gescoped).

M1 verwaltet nur Metadaten. Der echte Binär-Upload mit Textextraktion/FTS-Index
(upload→store→extract→index→link) ist Meilenstein 5 und ruft denselben
build_storage_path()-Helfer auf. Fehlt stored_path, wird hier ein provisorischer
Pfad erzeugt (siehe README: offene Frage 'Klasse' vs. 'Klassenstufe').
"""
import hashlib
import mimetypes
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from ..config import settings
from ..deps import get_db, get_storage_root, get_user_id, row_or_404
from ..lib.extract import extract_chunks
from ..lib.storage_path import build_storage_path
from ..schemas import MaterialCreate, MaterialLink, MaterialOut, MaterialUpdate, SearchHit

router = APIRouter(prefix="/materials", tags=["materials"])
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


def _unique_path(path: str) -> str:
    """Bei Kollision Suffix ' (n)' vor der Endung anhängen."""
    if not os.path.exists(path):
        return path
    p = Path(path)
    stem, suffix, parent = p.stem, p.suffix, p.parent
    n = 2
    while True:
        cand = parent / f"{stem} ({n}){suffix}"
        if not cand.exists():
            return str(cand)
        n += 1


def _get(conn, user_id, mid):
    row = conn.execute(
        "SELECT * FROM materials WHERE id = ? AND user_id = ?", (mid, user_id)
    ).fetchone()
    return MaterialOut(**dict(row)) if row else None


def _provisional_path(conn, user_id, body: MaterialCreate) -> str:
    year_label = "unsortiert"
    if body.school_year_id is not None:
        r = conn.execute(
            "SELECT label FROM school_years WHERE id = ? AND user_id = ?",
            (body.school_year_id, user_id),
        ).fetchone()
        if r:
            year_label = r["label"]
    klasse = f"Klasse-{body.grade}" if body.grade else "Allgemein"
    return build_storage_path(year_label, body.subject or "Allgemein", klasse, body.filename,
                              root=settings.storage_root)


@router.post("", response_model=MaterialOut, status_code=201)
def create(body: MaterialCreate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    stored_path = body.stored_path or _provisional_path(conn, user_id, body)
    try:
        cur = conn.execute(
            """INSERT INTO materials
               (user_id, filename, stored_path, mime_type, byte_size, sha256, subject,
                grade, school_year_id, lb_label, status, tag, external_link)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (user_id, body.filename, stored_path, body.mime_type, body.byte_size, body.sha256,
             body.subject, body.grade, body.school_year_id, body.lb_label, body.status,
             body.tag, body.external_link),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Material mit diesem Ablagepfad existiert bereits.")
    return _get(conn, user_id, cur.lastrowid)


@router.post("/upload", response_model=MaterialOut, status_code=201)
async def upload(
    file: UploadFile = File(...),
    subject: Optional[str] = Form(None),
    grade: Optional[int] = Form(None),
    school_year_id: Optional[int] = Form(None, alias="schoolYearId"),
    lb_label: Optional[str] = Form(None, alias="lbLabel"),
    status: str = Form("neu"),
    tag: Optional[str] = Form(None),
    external_link: Optional[str] = Form(None, alias="externalLink"),
    lesson_id: Optional[int] = Form(None, alias="lessonId"),
    lernbereich_id: Optional[int] = Form(None, alias="lernbereichId"),
    conn: sqlite3.Connection = Depends(get_db),
    user_id: int = Depends(get_user_id),
    storage_root: str = Depends(get_storage_root),
):
    """Atomarer Ablauf: upload → store → extract (PDF) → index (FTS) → link."""
    year_label = "unsortiert"
    if school_year_id is not None:
        r = conn.execute("SELECT label FROM school_years WHERE id = ? AND user_id = ?",
                         (school_year_id, user_id)).fetchone()
        if r:
            year_label = r["label"]
    klasse = f"Klasse-{grade}" if grade else "Allgemein"
    target = _unique_path(build_storage_path(
        year_label, subject or "Allgemein", klasse, file.filename or "datei", root=storage_root))

    # 1. Temp im selben Dateisystem wie das Ziel → atomarer os.replace
    tmp_dir = Path(storage_root) / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / f"{uuid.uuid4().hex}.part"
    sha, size = hashlib.sha256(), 0
    try:
        with open(tmp, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Datei zu groß (max. 50 MB).")
                sha.update(chunk)
                out.write(chunk)
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, target)  # 2. store (atomar)
    except HTTPException:
        if tmp.exists():
            tmp.unlink()
        raise
    except Exception as exc:  # pragma: no cover
        if tmp.exists():
            tmp.unlink()
        raise HTTPException(status_code=500, detail=f"Upload fehlgeschlagen: {exc}")

    mime = file.content_type or mimetypes.guess_type(file.filename or "")[0]
    try:  # 3. Metadaten-Zeile
        cur = conn.execute(
            """INSERT INTO materials(user_id, filename, stored_path, mime_type, byte_size, sha256,
               subject, grade, school_year_id, lb_label, status, tag, external_link)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (user_id, file.filename or "datei", target, mime, size, sha.hexdigest(),
             subject, grade, school_year_id, lb_label, status, tag, external_link),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        if os.path.exists(target):
            os.remove(target)  # Kompensation
        raise HTTPException(status_code=409, detail="Material mit diesem Ablagepfad existiert bereits.")
    mid = cur.lastrowid

    # 4. extract + index (nur PDF; best-effort)
    is_pdf = (mime or "").lower() == "application/pdf" or (file.filename or "").lower().endswith(".pdf")
    if is_pdf:
        try:
            for i, ch in enumerate(extract_chunks(target)):
                conn.execute(
                    "INSERT INTO material_chunks(material_id, chunk_index, page_from, page_to, content) VALUES (?,?,?,?,?)",
                    (mid, i, ch["page_from"], ch["page_to"], ch["content"]),
                )
            conn.execute("UPDATE materials SET extracted = 1 WHERE id = ?", (mid,))
            conn.commit()
        except Exception:  # pragma: no cover - defekte/gescannte PDFs bleiben ohne Chunks
            conn.rollback()

    # 5. link (Direkt-Upload aus Stunde/Stoffplan)
    if lesson_id is not None and conn.execute(
            "SELECT 1 FROM lessons WHERE id = ? AND user_id = ?", (lesson_id, user_id)).fetchone():
        conn.execute("INSERT OR IGNORE INTO material_lessons(material_id, lesson_id) VALUES (?,?)", (mid, lesson_id))
    if lernbereich_id is not None and conn.execute(
            "SELECT 1 FROM lernbereiche WHERE id = ?", (lernbereich_id,)).fetchone():
        conn.execute("INSERT OR IGNORE INTO material_lernbereiche(material_id, lernbereich_id) VALUES (?,?)", (mid, lernbereich_id))
    conn.commit()
    return _get(conn, user_id, mid)


@router.get("/search", response_model=List[SearchHit])
def search(
    q: str,
    subject: Optional[str] = None,
    grade: Optional[int] = None,
    lernbereich_id: Optional[int] = Query(None, alias="lernbereichId"),
    limit: int = 4,
    conn: sqlite3.Connection = Depends(get_db),
    user_id: int = Depends(get_user_id),
):
    """Gezielter Volltext-Abruf (FTS5) – Grundlage für den KI-Kontext in M7."""
    terms = " ".join(f'"{w}"' for w in q.split() if w)
    if not terms:
        return []
    parts = [
        "SELECT m.id AS material_id, m.filename, mc.page_from, mc.page_to,",
        " snippet(material_chunks_fts, 0, '[', ']', '…', 12) AS snippet",
        "FROM material_chunks_fts",
        "JOIN material_chunks mc ON mc.id = material_chunks_fts.rowid",
        "JOIN materials m ON m.id = mc.material_id",
    ]
    where = ["material_chunks_fts MATCH ?", "m.user_id = ?"]
    params = [terms, user_id]
    if lernbereich_id is not None:
        parts.append("JOIN material_lernbereiche ml ON ml.material_id = m.id")
        where.append("ml.lernbereich_id = ?")
        params.append(lernbereich_id)
    if subject is not None:
        where.append("m.subject = ?")
        params.append(subject)
    if grade is not None:
        where.append("m.grade = ?")
        params.append(grade)
    query = " ".join(parts) + " WHERE " + " AND ".join(where) + " ORDER BY bm25(material_chunks_fts) LIMIT ?"
    params.append(limit)
    try:
        rows = conn.execute(query, params).fetchall()
    except sqlite3.OperationalError as exc:
        raise HTTPException(status_code=400, detail=f"Ungültige Suchanfrage: {exc}")
    return [SearchHit(material_id=r["material_id"], filename=r["filename"],
                      page_from=r["page_from"], page_to=r["page_to"], snippet=r["snippet"]) for r in rows]


@router.get("/{mid}/download")
def download(mid: int, conn: sqlite3.Connection = Depends(get_db), user_id: int = Depends(get_user_id)):
    row = row_or_404(
        conn.execute("SELECT stored_path, filename, mime_type FROM materials WHERE id = ? AND user_id = ?",
                     (mid, user_id)).fetchone(), "Material")
    if not os.path.exists(row["stored_path"]):
        raise HTTPException(status_code=404, detail="Datei nicht auf dem Speicher gefunden.")
    return FileResponse(row["stored_path"], filename=row["filename"],
                        media_type=row["mime_type"] or "application/octet-stream")


@router.get("", response_model=List[MaterialOut])
def list_(
    subject: Optional[str] = None,
    grade: Optional[int] = None,
    lernbereich_id: Optional[int] = Query(None, alias="lernbereichId"),
    conn=Depends(get_db),
    user_id: int = Depends(get_user_id),
):
    if lernbereich_id is not None:
        sql = ("SELECT m.* FROM materials m "
               "JOIN material_lernbereiche ml ON ml.material_id = m.id "
               "WHERE m.user_id = ? AND ml.lernbereich_id = ?")
        params = [user_id, lernbereich_id]
    else:
        sql = "SELECT * FROM materials WHERE user_id = ?"
        params = [user_id]
        if subject is not None:
            sql += " AND subject = ?"
            params.append(subject)
        if grade is not None:
            sql += " AND grade = ?"
            params.append(grade)
    sql += " ORDER BY m.id" if lernbereich_id is not None else " ORDER BY id"
    return [MaterialOut(**dict(r)) for r in conn.execute(sql, params).fetchall()]


@router.get("/{mid}", response_model=MaterialOut)
def get_(mid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    return row_or_404(_get(conn, user_id, mid), "Material")


@router.put("/{mid}", response_model=MaterialOut)
def update(mid: int, body: MaterialUpdate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get(conn, user_id, mid), "Material")
    fields = body.model_dump(exclude_unset=True)
    if fields:
        cols = ", ".join(f"{k} = :{k}" for k in fields)
        fields.update(id=mid, uid=user_id)
        conn.execute(
            f"UPDATE materials SET {cols}, updated_at = datetime('now') WHERE id = :id AND user_id = :uid",
            fields,
        )
        conn.commit()
    return _get(conn, user_id, mid)


@router.delete("/{mid}", status_code=204)
def delete(mid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    cur = conn.execute("DELETE FROM materials WHERE id = ? AND user_id = ?", (mid, user_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Material nicht gefunden.")


# ---------- Verknüpfungen ----------
def _owned_material(conn, user_id, mid):
    row_or_404(
        conn.execute("SELECT 1 FROM materials WHERE id = ? AND user_id = ?", (mid, user_id)).fetchone(),
        "Material",
    )


@router.get("/{mid}/links")
def get_links(mid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)) -> Dict[str, List[int]]:
    _owned_material(conn, user_id, mid)
    lessons = [r[0] for r in conn.execute(
        "SELECT lesson_id FROM material_lessons WHERE material_id = ? ORDER BY lesson_id", (mid,))]
    lbs = [r[0] for r in conn.execute(
        "SELECT lernbereich_id FROM material_lernbereiche WHERE material_id = ? ORDER BY lernbereich_id", (mid,))]
    return {"lessons": lessons, "lernbereiche": lbs}


@router.post("/{mid}/links", status_code=200)
def add_links(mid: int, body: MaterialLink, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    _owned_material(conn, user_id, mid)
    if body.lesson_id is not None:
        row_or_404(
            conn.execute("SELECT 1 FROM lessons WHERE id = ? AND user_id = ?",
                         (body.lesson_id, user_id)).fetchone(), "Stunde")
        conn.execute("INSERT OR IGNORE INTO material_lessons(material_id, lesson_id) VALUES (?,?)",
                     (mid, body.lesson_id))
    if body.lernbereich_id is not None:
        row_or_404(
            conn.execute("SELECT 1 FROM lernbereiche WHERE id = ?", (body.lernbereich_id,)).fetchone(),
            "Lernbereich")
        conn.execute("INSERT OR IGNORE INTO material_lernbereiche(material_id, lernbereich_id) VALUES (?,?)",
                     (mid, body.lernbereich_id))
    conn.commit()
    return get_links(mid, conn, user_id)


@router.delete("/{mid}/links", status_code=200)
def remove_links(mid: int, body: MaterialLink, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    _owned_material(conn, user_id, mid)
    if body.lesson_id is not None:
        conn.execute("DELETE FROM material_lessons WHERE material_id = ? AND lesson_id = ?",
                     (mid, body.lesson_id))
    if body.lernbereich_id is not None:
        conn.execute("DELETE FROM material_lernbereiche WHERE material_id = ? AND lernbereich_id = ?",
                     (mid, body.lernbereich_id))
    conn.commit()
    return get_links(mid, conn, user_id)
