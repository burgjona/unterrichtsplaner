import sqlite3
import threading

import pytest

from src.db import connect, init_db


def test_connection_is_cross_thread_safe(tmp_path):
    # Regression: FastAPI löst sync-Dependencies im Threadpool auf – die per-Request-
    # Connection muss über Threads hinweg nutzbar sein (check_same_thread=False).
    conn = init_db(str(tmp_path / "thread.db"))
    result = []
    t = threading.Thread(target=lambda: result.append(conn.execute("SELECT 1").fetchone()[0]))
    t.start()
    t.join()
    conn.close()
    assert result == [1]


@pytest.fixture
def conn(tmp_path):
    c = init_db(str(tmp_path / "schema.db"))
    yield c
    c.close()


def _make_user(conn):
    cur = conn.execute("INSERT INTO users(email, display_name) VALUES ('a@b.de','A')")
    conn.commit()
    return cur.lastrowid


def test_integrity_and_fts_table_exist(conn):
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    assert "material_chunks_fts" in names


def test_foreign_key_enforced(conn):
    # Material mit nicht existierendem user_id muss scheitern.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO materials(user_id, filename, stored_path) VALUES (9999,'x.pdf','/p/x.pdf')"
        )
        conn.commit()


def test_fts_trigger_roundtrip(conn):
    uid = _make_user(conn)
    mid = conn.execute(
        "INSERT INTO materials(user_id, filename, stored_path) VALUES (?, 'l.pdf', '/p/l.pdf')",
        (uid,),
    ).lastrowid
    conn.execute(
        "INSERT INTO material_chunks(material_id, chunk_index, content, heading) "
        "VALUES (?, 0, 'Die Ballade als episch-lyrische Mischform', 'Balladen')",
        (mid,),
    )
    conn.commit()

    hit = conn.execute(
        "SELECT rowid FROM material_chunks_fts WHERE material_chunks_fts MATCH 'ballade'"
    ).fetchall()
    assert len(hit) == 1  # remove_diacritics/lowercasing greift

    # Update spiegelt sich im Index
    conn.execute("UPDATE material_chunks SET content = 'Nur noch Prosa' WHERE id = ?", (hit[0][0],))
    conn.commit()
    assert conn.execute(
        "SELECT COUNT(*) FROM material_chunks_fts WHERE material_chunks_fts MATCH 'ballade'"
    ).fetchone()[0] == 0

    # Delete entfernt den Eintrag aus dem Index
    conn.execute("DELETE FROM material_chunks WHERE id = ?", (hit[0][0],))
    conn.commit()
    assert conn.execute(
        "SELECT COUNT(*) FROM material_chunks_fts WHERE material_chunks_fts MATCH 'prosa'"
    ).fetchone()[0] == 0


def test_cascade_delete_chunks_with_material(conn):
    uid = _make_user(conn)
    mid = conn.execute(
        "INSERT INTO materials(user_id, filename, stored_path) VALUES (?, 'l.pdf', '/p/l2.pdf')",
        (uid,),
    ).lastrowid
    conn.execute(
        "INSERT INTO material_chunks(material_id, chunk_index, content) VALUES (?,0,'text')", (mid,)
    )
    conn.commit()
    conn.execute("DELETE FROM materials WHERE id = ?", (mid,))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM material_chunks").fetchone()[0] == 0
