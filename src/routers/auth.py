"""Registrierung, Login, Logout, aktueller Nutzer.

Bootstrap-Register: /auth/register funktioniert nur, solange es 0 Konten gibt;
danach ist die Registrierung gesperrt (genau ein Account, BRIEFING Kap. 2 M2).
Sessions sind serverseitig (Tabelle sessions) mit opakem Token im HttpOnly-Cookie.
"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..config import settings
from ..deps import get_db, get_user_id
from ..lib import loginguard
from ..lib.security import dummy_verify, generate_token, hash_password, verify_password
from ..schemas import LoginIn, PasswordChangeIn, RegisterIn, UserOut
from . import calendar_categories

router = APIRouter(prefix="/auth", tags=["auth"])

MIN_PASSWORD_LENGTH = 8


def _require_password_length(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen haben.")


def _start_session(conn: sqlite3.Connection, response: Response, user_id: int) -> None:
    # Housekeeping (M9.1): abgelaufene Sessions bei jeder Neuanmeldung entsorgen,
    # damit die Tabelle nicht unbegrenzt wächst.
    conn.execute("DELETE FROM sessions WHERE expires_at <= datetime('now')")
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
    _require_password_length(body.password)
    try:
        cur = conn.execute(
            "INSERT INTO users(email, display_name, password_hash) VALUES (?, ?, ?)",
            (body.email, body.display_name, hash_password(body.password)),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="E-Mail bereits vergeben.")
    # Standard-Kalender-Kategorien hier statt beim ersten GET /calendar-categories seeden:
    # seit dem Offline-Sync-Rollout liest das Frontend Kategorien über die Sync-Engine
    # (GET /sync/changes), das lazy-Seeding im REST-List-Endpunkt würde also nie mehr feuern.
    calendar_categories._seed_defaults(conn, cur.lastrowid)
    _start_session(conn, response, cur.lastrowid)  # direkt eingeloggt
    return _user_out(conn, cur.lastrowid)


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response,
          conn: sqlite3.Connection = Depends(get_db)):
    ip = loginguard.client_ip(request)
    if loginguard.is_locked(conn, body.email, ip):
        # Vor der Passwortpruefung: sonst wäre die Sperre gegen genau das wirkungslos,
        # was sie verhindern soll (das Durchprobieren von Passwörtern).
        raise HTTPException(
            status_code=429,
            detail=f"Zu viele Fehlversuche. Bitte in {loginguard.WINDOW_MINUTES} Minuten erneut versuchen.",
            headers={"Retry-After": str(loginguard.WINDOW_MINUTES * 60)},
        )

    row = conn.execute(
        "SELECT id, password_hash FROM users WHERE email = ?", (body.email,)
    ).fetchone()
    if row is None or not row["password_hash"]:
        # Gleich lange rechnen wie bei existierender E-Mail. Ohne das verraet die
        # Antwortzeit (argon2 braucht ~100 ms), ob eine Adresse registriert ist.
        dummy_verify(body.password)
        loginguard.record_failure(conn, body.email, ip)
        raise HTTPException(status_code=401, detail="E-Mail oder Passwort ist falsch.")
    if not verify_password(row["password_hash"], body.password):
        loginguard.record_failure(conn, body.email, ip)
        raise HTTPException(status_code=401, detail="E-Mail oder Passwort ist falsch.")

    loginguard.clear(conn, body.email, ip)
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


@router.post("/password")
def change_password(body: PasswordChangeIn, request: Request,
                    conn: sqlite3.Connection = Depends(get_db),
                    user_id: int = Depends(get_user_id)):
    """Passwort ändern. Meldet danach alle ANDEREN Sitzungen ab - wer das Passwort
    wechselt, will in aller Regel genau die fremden Geraete loswerden; die eigene
    Sitzung bleibt bestehen, damit man nicht aus der laufenden App fliegt."""
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row or not row["password_hash"] or not verify_password(row["password_hash"],
                                                                  body.current_password):
        raise HTTPException(status_code=401, detail="Aktuelles Passwort ist falsch.")
    _require_password_length(body.new_password)
    if body.new_password == body.current_password:
        raise HTTPException(status_code=400,
                            detail="Das neue Passwort muss sich vom bisherigen unterscheiden.")

    conn.execute("UPDATE users SET password_hash = ?, updated_at = datetime('now') WHERE id = ?",
                 (hash_password(body.new_password), user_id))
    token = request.cookies.get(settings.cookie_name)
    cur = conn.execute("DELETE FROM sessions WHERE user_id = ? AND token IS NOT ?",
                       (user_id, token))
    conn.commit()
    return {"ok": True, "loggedOutDevices": cur.rowcount}


@router.get("/me", response_model=UserOut)
def me(conn: sqlite3.Connection = Depends(get_db), user_id: int = Depends(get_user_id)):
    return _user_out(conn, user_id)
