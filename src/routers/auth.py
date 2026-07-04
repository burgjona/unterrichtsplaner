"""Registrierung, Login, Logout, aktueller Nutzer.

Bootstrap-Register: /auth/register funktioniert nur, solange es 0 Konten gibt;
danach ist die Registrierung gesperrt (genau ein Account, BRIEFING Kap. 2 M2).
Sessions sind serverseitig (Tabelle sessions) mit opakem Token im HttpOnly-Cookie.
"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..config import settings
from ..deps import get_db, get_user_id
from ..lib.security import generate_token, hash_password, verify_password
from ..schemas import LoginIn, RegisterIn, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _start_session(conn: sqlite3.Connection, response: Response, user_id: int) -> None:
    token = generate_token()
    conn.execute(
        "INSERT INTO sessions(token, user_id, expires_at) VALUES (?, ?, datetime('now', ?))",
        (token, user_id, f"+{settings.session_ttl_hours} hours"),
    )
    conn.commit()
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def _user_out(conn, user_id) -> UserOut:
    return UserOut(**dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()))


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterIn, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
        raise HTTPException(status_code=403, detail="Registrierung ist deaktiviert (Konto existiert bereits).")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Passwort muss mindestens 8 Zeichen haben.")
    try:
        cur = conn.execute(
            "INSERT INTO users(email, display_name, password_hash) VALUES (?, ?, ?)",
            (body.email, body.display_name, hash_password(body.password)),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="E-Mail bereits vergeben.")
    _start_session(conn, response, cur.lastrowid)  # direkt eingeloggt
    return _user_out(conn, cur.lastrowid)


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute(
        "SELECT id, password_hash FROM users WHERE email = ?", (body.email,)
    ).fetchone()
    if row is None or not row["password_hash"] or not verify_password(row["password_hash"], body.password):
        raise HTTPException(status_code=401, detail="E-Mail oder Passwort ist falsch.")
    _start_session(conn, response, row["id"])
    return _user_out(conn, row["id"])


@router.post("/logout")
def logout(request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db),
           user_id: int = Depends(get_user_id)):
    token = request.cookies.get(settings.cookie_name)
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    response.delete_cookie(settings.cookie_name, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(conn: sqlite3.Connection = Depends(get_db), user_id: int = Depends(get_user_id)):
    return _user_out(conn, user_id)
