"""Claude-API-Schicht: Modell-Routing, Prompt-Cache, gezielter FTS-Kontext, Kosten-Logging.

Modellwahl ist pro Funktion fest hinterlegt (BRIEFING Kap. 5). Der nutzereigene
API-Key wird pro Aufruf aus user_settings entschlüsselt (M2). Ein lokaler
Prompt-Cache (template + Kontext-Hash) vermeidet erneute Calls für identische Prompts;
zusätzlich cached die Anthropic-API den stabilen System-Prompt (cache_control).
Nie Volltext an die KI – nur Top-K-Abschnitte via FTS5 (BRIEFING Kap. 5/M5).
"""
import hashlib
import json
import sqlite3
from typing import List, Optional

from .security import decrypt_secret

MODELS = {"haiku": "claude-haiku-4-5", "sonnet": "claude-sonnet-4-6", "opus": "claude-opus-4-8"}

# USD je 1 Mio. Tokens (Input, Output) – Stand API-Referenz
PRICING = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-8": (5.0, 25.0),
}

# Funktion -> Modell, fest hinterlegt (BRIEFING Kap. 5; ASUV=Sonnet per Nutzerentscheidung)
ROUTING = {
    "lesson_suggestion": "sonnet",   # Klafki-Erstentwurf + Meyer/Phasen
    "stoffplan": "sonnet",           # Stoffverteilungsplan-Generierung
    "asuv": "sonnet",                # ASUV-Ausformulierung
    "lernziele": "sonnet",           # SMARTe Lernziele nach Bloom-Taxonomie
    "einordnung": "haiku",           # kurze Lernbereichs-/Lernziel-Verortung freier Stunden
    "jahresplan_import": "sonnet",   # Termin-Erkennung aus dem Schul-Jahresplan (PDF) — U20
}

_prompt_cache = {}  # sha256(prompt) -> Antworttext (lokal, prozessweit)


class NoApiKey(Exception):
    """Kein Anthropic-Key hinterlegt."""


def get_api_key(conn: sqlite3.Connection, user_id: int) -> Optional[str]:
    row = conn.execute(
        "SELECT anthropic_key_cipher, anthropic_key_nonce FROM user_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if not row or not row["anthropic_key_cipher"]:
        return None
    try:
        return decrypt_secret(row["anthropic_key_cipher"], row["anthropic_key_nonce"])
    except Exception:
        return None


def _make_client(api_key: str):  # in Tests gemockt
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def fts_context(conn, user_id, query, subject=None, grade=None, limit=3) -> List[dict]:
    """Top-K relevante Abschnitte aus Begleitmaterialien (FTS5) – Grundlage statt Volltext."""
    terms = " ".join(f'"{w}"' for w in (query or "").split() if w)
    if not terms:
        return []
    where = ["material_chunks_fts MATCH ?", "m.user_id = ?"]
    params = [terms, user_id]
    if subject:
        where.append("m.subject = ?")
        params.append(subject)
    if grade:
        where.append("m.grade = ?")
        params.append(grade)
    sql = ("SELECT m.filename, mc.page_from, mc.content FROM material_chunks_fts "
           "JOIN material_chunks mc ON mc.id = material_chunks_fts.rowid "
           "JOIN materials m ON m.id = mc.material_id WHERE " + " AND ".join(where) +
           " ORDER BY bm25(material_chunks_fts) LIMIT ?")
    params.append(limit)
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.OperationalError:
        return []


def run(conn, user_id, function, system, user_text, schema=None, max_tokens=2000) -> dict:
    """Führt einen KI-Call aus (mit lokalem Cache + Kosten-Logging). Wirft NoApiKey ohne Key."""
    api_key = get_api_key(conn, user_id)
    if not api_key:
        raise NoApiKey()
    model = MODELS[ROUTING[function]]
    cache_key = hashlib.sha256(
        f"{function}|{model}|{system}|{user_text}|{json.dumps(schema, sort_keys=True)}".encode()
    ).hexdigest()
    if cache_key in _prompt_cache:
        return {"text": _prompt_cache[cache_key], "cached": True}

    client = _make_client(api_key)
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_text}],
    )
    if schema:
        kwargs["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
    resp = client.messages.create(**kwargs)

    text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), "")
    usage = resp.usage
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    p_in, p_out = PRICING.get(model, (0.0, 0.0))
    cost = (inp * p_in + out * p_out + cache_read * p_in * 0.1) / 1_000_000
    conn.execute(
        """INSERT INTO ai_usage(user_id, function, model, input_tokens, output_tokens,
           cache_read_tokens, cost_usd) VALUES (?,?,?,?,?,?,?)""",
        (user_id, function, model, inp, out, cache_read, cost),
    )
    conn.commit()
    _prompt_cache[cache_key] = text
    return {"text": text, "cached": False}
