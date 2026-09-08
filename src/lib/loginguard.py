"""Brute-Force-Bremse für den Login (U28).

Zwei Schwellen, weil keine allein taugt:

* pro IP (5/15 min) - fängt den Normalfall, den Bot, der Passwortlisten durchprobiert.
* pro Konto (10/15 min) - Notbremse, falls die IP-Zählung umgangen wird. Denn hinter dem
  Cloudflare-Tunnel steht die echte Client-IP nur im Header CF-Connecting-IP, und Header
  sind fälschbar, sobald jemand die App im LAN direkt auf Port 8097 erreicht.

Der Preis der Kontoschwelle: wer die E-Mail kennt, kann den Nutzer mit Absicht für 15
Minuten aussperren. Bewusst in Kauf genommen - der Bot ist das wahrscheinlichere Problem,
und 10 Versuche je Viertelstunde bremsen ihn wirksam, ohne beim Vertippen zu stören.
"""
from __future__ import annotations

import sqlite3

from fastapi import Request

WINDOW_MINUTES = 15
MAX_PER_IP = 5
MAX_PER_EMAIL = 10
KEEP_HOURS = 24          # ältere Einträge sind wertlos - beim Login mit aufräumen
UNKNOWN_IP = "unbekannt"


def client_ip(request: Request) -> str:
    """Echte Client-IP. Hinter dem Cloudflare-Tunnel sehen alle Anfragen sonst gleich aus:
    request.client.host wäre die Container-IP des Tunnels und damit als Merkmal wertlos."""
    forwarded = request.headers.get("cf-connecting-ip")
    if forwarded:
        return forwarded.strip()[:64]
    if request.client and request.client.host:
        return request.client.host[:64]
    return UNKNOWN_IP


def _count(conn: sqlite3.Connection, column: str, value: str) -> int:
    return conn.execute(
        f"SELECT COUNT(*) FROM login_attempts "
        f"WHERE {column} = ? AND created_at > datetime('now', ?)",
        (value, f"-{WINDOW_MINUTES} minutes"),
    ).fetchone()[0]


def is_locked(conn: sqlite3.Connection, email: str, ip: str) -> bool:
    """True, sobald eine der beiden Schwellen im Zeitfenster gerissen ist."""
    return (_count(conn, "ip", ip) >= MAX_PER_IP
            or _count(conn, "email", email) >= MAX_PER_EMAIL)


def record_failure(conn: sqlite3.Connection, email: str, ip: str) -> None:
    conn.execute("DELETE FROM login_attempts WHERE created_at <= datetime('now', ?)",
                 (f"-{KEEP_HOURS} hours",))
    conn.execute("INSERT INTO login_attempts(email, ip) VALUES (?, ?)", (email, ip))
    conn.commit()


def clear(conn: sqlite3.Connection, email: str, ip: str) -> None:
    """Nach erfolgreichem Login: Zähler dieser IP UND dieses Kontos zurücksetzen -
    sonst bliebe der Nutzer nach ein paar Tippfehlern unnötig gesperrt."""
    conn.execute("DELETE FROM login_attempts WHERE ip = ? OR email = ?", (ip, email))
    conn.commit()
