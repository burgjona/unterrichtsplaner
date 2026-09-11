"""Web-Push M2: Erinnerungen 5 Min. vorher + Schulmanager-Abgleich (Versand gemockt)."""
import datetime as dt

import pytest

from src.db import connect
from src.lib import notifier, push, schulmanager_diff, schulmanager_ical

STUNDENPLAN = "/api/stundenplan"


def _conn(client):
    return connect(client.app.state.db_path)


def _monday() -> dt.date:
    today = dt.date.today()
    return today - dt.timedelta(days=today.weekday())


def _at(day: dt.date, hhmm: str, delta=dt.timedelta(0)) -> dt.datetime:
    return dt.datetime.combine(day, dt.datetime.strptime(hhmm, "%H:%M").time()) + delta


BEFORE_5 = -dt.timedelta(minutes=5) + dt.timedelta(seconds=1)   # Takt kurz nach 07:25
BEFORE_6 = -dt.timedelta(minutes=6) + dt.timedelta(seconds=1)


@pytest.fixture
def device(client, user_id):
    conn = _conn(client)
    conn.execute("INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth) "
                 "VALUES (?, 'https://web.push.apple.com/x', 'k', 'a')", (user_id,))
    conn.commit()


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake(conn, user_id, title, body, url="/", tag=None):
        calls.append({"title": title, "body": body, "tag": tag})
        return {"sent": 1, "failed": 0, "removed": 0}

    monkeypatch.setattr(push, "send_to_user", fake)
    return calls


def _entry(client, kind_name="Unterricht", slot_index=1, with_class=True, room=None, weekday=0):
    kinds = client.get(f"{STUNDENPLAN}/kinds").json()
    slots = client.get(f"{STUNDENPLAN}/slots").json()
    plans = client.get(f"{STUNDENPLAN}/plans").json()
    payload = {"planId": plans[0]["id"], "slotId": slots[slot_index]["id"], "weekday": weekday,
               "kindId": next(k["id"] for k in kinds if k["name"] == kind_name)}
    if with_class:
        cls = client.post("/api/classes", json={"name": "8a", "subject": "Deutsch", "grade": 8}).json()
        payload["classId"] = cls["id"]
    if room:
        payload["room"] = room
    r = client.post(f"{STUNDENPLAN}/entries", json=payload)
    assert r.status_code in (200, 201), r.text
    return slots[slot_index]


def _calendar(client, user_id, title, day, start, end=None, room=None):
    conn = _conn(client)
    conn.execute("INSERT INTO calendar_entries (user_id, title, entry_date, start_time, end_time, "
                 "all_day, room) VALUES (?, ?, ?, ?, ?, 0, ?)",
                 (user_id, title, day.isoformat(), start, end, room))
    conn.commit()


# ---------------------------------------------------------------- Erinnerungen
def test_lesson_reminder_five_minutes_before(client, auth, device, sent):
    slot = _entry(client, room="204")
    notifier.run_reminders(_conn(client), _at(_monday(), slot["startTime"], BEFORE_5))
    assert len(sent) == 1
    assert sent[0]["title"] == "8a Deutsch in 5 Min."
    assert sent[0]["body"] == f"1. Stunde · {slot['startTime']}–{slot['endTime']} · Raum 204"


def test_reminder_not_too_early_and_only_once(client, auth, device, sent):
    slot = _entry(client)
    conn = _conn(client)
    notifier.run_reminders(conn, _at(_monday(), slot["startTime"], BEFORE_6))
    assert sent == []
    notifier.run_reminders(conn, _at(_monday(), slot["startTime"], BEFORE_5))
    notifier.run_reminders(conn, _at(_monday(), slot["startTime"], -dt.timedelta(minutes=4)))
    assert len(sent) == 1


def test_missed_tick_still_reminds_with_actual_minutes(client, auth, device, sent):
    slot = _entry(client)
    notifier.run_reminders(_conn(client), _at(_monday(), slot["startTime"], -dt.timedelta(minutes=2)))
    assert sent[0]["title"] == "8a Deutsch in 2 Min."


def test_no_reminder_without_device(client, auth, sent):
    slot = _entry(client)
    notifier.run_reminders(_conn(client), _at(_monday(), slot["startTime"], BEFORE_5))
    assert sent == []


def test_supervision_from_timetable(client, auth, device, sent):
    slot = _entry(client, kind_name="Aufsicht", slot_index=0, with_class=False, room="Hof")
    notifier.run_reminders(_conn(client), _at(_monday(), slot["startTime"], BEFORE_5))
    assert sent[0]["title"] == "Aufsicht in 5 Min."
    assert sent[0]["body"] == f"{slot['startTime']}–{slot['endTime']} · Hof"


def test_every_timetable_kind_is_reminded(client, auth, device, sent):
    slot = _entry(client, kind_name="Dienstberatung/Konferenz", with_class=False, room="Aula")
    notifier.run_reminders(_conn(client), _at(_monday(), slot["startTime"], BEFORE_5))
    assert sent[0]["title"] == "Dienstberatung/Konferenz in 5 Min."
    assert sent[0]["body"].endswith("· Aula")  # ohne Klasse kein "Raum"-Präfix


def test_supervision_from_calendar(client, auth, user_id, device, sent):
    _calendar(client, user_id, "Aufsicht: Ebene 1", _monday(), "09:20", "09:35", "Ebene 1: Cafeteria")
    notifier.run_reminders(_conn(client), _at(_monday(), "09:20", BEFORE_5))
    assert sent[0]["title"] == "Aufsicht in 5 Min."
    assert sent[0]["body"] == "Aufsicht: Ebene 1 · 09:20–09:35 · Ebene 1: Cafeteria"


def test_calendar_appointment_with_time(client, auth, user_id, device, sent):
    _calendar(client, user_id, "Elterngespräch Müller", _monday(), "14:00", "14:30", "Lehrerzimmer")
    conn = _conn(client)
    conn.execute("INSERT INTO calendar_entries (user_id, title, entry_date) VALUES (?, 'Wandertag', ?)",
                 (user_id, _monday().isoformat()))  # ganztägig -> keine Erinnerung
    conn.commit()
    notifier.run_reminders(conn, _at(_monday(), "14:00", BEFORE_5))
    assert [(s["title"], s["body"]) for s in sent] == [
        ("Elterngespräch Müller in 5 Min.", "14:00–14:30 · Lehrerzimmer")]


def test_same_start_in_timetable_and_calendar_prefers_timetable(client, auth, user_id, device, sent):
    slot = _entry(client)
    _calendar(client, user_id, "Balladen – Einstieg", _monday(), slot["startTime"])
    notifier.run_reminders(_conn(client), _at(_monday(), slot["startTime"], BEFORE_5))
    assert [s["title"] for s in sent] == ["8a Deutsch in 5 Min."]


def test_same_supervision_in_timetable_and_calendar_notifies_once(client, auth, user_id, device, sent):
    slot = _entry(client, kind_name="Aufsicht", slot_index=0, with_class=False)
    _calendar(client, user_id, "Aufsicht", _monday(), slot["startTime"])
    notifier.run_reminders(_conn(client), _at(_monday(), slot["startTime"], BEFORE_5))
    assert len(sent) == 1


def test_holidays_silence_timetable_but_not_calendar(client, auth, user_id, device, sent, monkeypatch):
    slot = _entry(client)
    _calendar(client, user_id, "Fortbildung", _monday(), "10:00")
    iso = _monday().isoformat()
    monkeypatch.setattr(schulmanager_diff, "_load_holiday_ranges", lambda conn, uid: [(iso, iso)])
    conn = _conn(client)
    notifier.run_reminders(conn, _at(_monday(), slot["startTime"], BEFORE_5))
    assert sent == []
    notifier.run_reminders(conn, _at(_monday(), "10:00", BEFORE_5))
    assert [s["title"] for s in sent] == ["Fortbildung in 5 Min."]


def test_no_reminders_on_absence_days(client, auth, user_id, device, sent):
    slot = _entry(client)
    _calendar(client, user_id, "Dienstberatung", _monday(), "14:00")
    conn = _conn(client)
    conn.execute("INSERT INTO absences (user_id, kind, start_date, end_date) VALUES (?, 'krank', ?, ?)",
                 (user_id, _monday().isoformat(), _monday().isoformat()))
    conn.commit()
    notifier.run_reminders(conn, _at(_monday(), slot["startTime"], BEFORE_5))
    notifier.run_reminders(conn, _at(_monday(), "14:00", BEFORE_5))
    assert sent == []


def test_weekend_reminds_calendar_appointments(client, auth, user_id, device, sent):
    saturday = _monday() + dt.timedelta(days=5)
    _calendar(client, user_id, "Schulfest Aufbau", saturday, "10:00")
    notifier.run_reminders(_conn(client), _at(saturday, "10:00", BEFORE_5))
    assert [s["title"] for s in sent] == ["Schulfest Aufbau in 5 Min."]


# ---------------------------------------------------------------- Schulmanager
@pytest.fixture
def feed(client, user_id, monkeypatch):
    """Hinterlegter ICS-Link + gemockter Abruf; changes['…'] vom Test befüllbar."""
    conn = _conn(client)
    conn.execute("INSERT INTO user_settings (user_id, schulmanager_ical_cipher, schulmanager_ical_nonce) "
                 "VALUES (?, x'00', x'00') ON CONFLICT(user_id) DO UPDATE SET "
                 "schulmanager_ical_cipher = x'00', schulmanager_ical_nonce = x'00'", (user_id,))
    conn.commit()
    state = {"calls": 0, "changes": {k: [] for k in notifier.CATEGORY_LABELS}}

    def fake_fetch(conn, uid):
        state["calls"] += 1
        return []

    monkeypatch.setattr(schulmanager_ical, "fetch_and_parse", fake_fetch)
    monkeypatch.setattr(schulmanager_diff, "compute_changes", lambda conn, uid, ev: state["changes"])
    return state


def _vertretung(day, start="12:45", end="13:30", title="DE (9a)", room="204"):
    return {"date": day.isoformat(), "start": start, "end": end, "expected": None,
            "actual": {"title": title, "room": room, "uid": "x"}, "class_id": None}


def test_new_vertretung_is_notified_once(client, auth, device, sent, feed):
    feed["changes"]["vertretung"] = [_vertretung(_monday())]
    conn = _conn(client)
    notifier.run_schulmanager(conn, _at(_monday(), "10:00"))
    notifier.run_schulmanager(conn, _at(_monday(), "10:15"))
    assert feed["calls"] == 2
    assert len(sent) == 1
    assert sent[0]["title"] == "Vertretung: DE (9a)"
    assert sent[0]["body"] == f"Mo {_monday().strftime('%d.%m.%Y')} · 12:45–13:30 · 204"


def test_changed_supervision_room_is_named(client, auth, device, sent, feed):
    feed["changes"]["aufsicht_geaendert"] = [
        {**_vertretung(_monday(), title="Aufsicht: Ebene 2", room="Ebene 2"), "entry_id": 1}]
    notifier.run_schulmanager(_conn(client), _at(_monday(), "10:00"))
    assert sent[0]["title"] == "Aufsicht geändert: Aufsicht: Ebene 2"
    assert sent[0]["body"].endswith("jetzt Ebene 2")


def test_past_changes_are_ignored(client, auth, device, sent, feed):
    feed["changes"]["ausfall"] = [{**_vertretung(_monday(), start="07:30"), "actual": None,
                                   "expected": {"title": "8a Deutsch", "room": "204"}}]
    notifier.run_schulmanager(_conn(client), _at(_monday(), "10:00"))
    assert sent == []


def test_polls_only_every_quarter_hour_on_school_hours(client, auth, device, sent, feed):
    conn = _conn(client)
    notifier.run_schulmanager(conn, _at(_monday(), "10:07"))
    notifier.run_schulmanager(conn, _at(_monday(), "19:00"))
    notifier.run_schulmanager(conn, _at(_monday() + dt.timedelta(days=6), "10:00"))  # Sonntag
    assert feed["calls"] == 0


def test_many_changes_become_one_summary(client, auth, device, sent, feed):
    tuesday = _monday() + dt.timedelta(days=1)
    feed["changes"]["vertretung"] = [_vertretung(tuesday, start=f"0{h}:00") for h in range(7, 10)]
    feed["changes"]["aufsicht_neu"] = [_vertretung(tuesday, start="11:00", title="Aufsicht: Hof"),
                                       _vertretung(tuesday, start="12:00", title="Aufsicht: Hof")]
    notifier.run_schulmanager(_conn(client), _at(_monday(), "10:00"))
    assert len(sent) == 1
    assert sent[0]["title"] == "Schulmanager: 5 neue Änderungen"
    assert sent[0]["body"].startswith(f"Vertretung Di {tuesday.strftime('%d.%m.')} 07:00")


def test_feed_error_does_not_break_the_tick(client, auth, device, sent, feed, monkeypatch):
    def boom(conn, uid):
        raise RuntimeError("Timeout")

    monkeypatch.setattr(schulmanager_ical, "fetch_and_parse", boom)
    notifier.run_schulmanager(_conn(client), _at(_monday(), "10:00"))
    assert sent == []


# ---------------------------------------------------------------- Takt
def test_tick_runs_both_steps(client, auth, device, sent, feed, monkeypatch):
    slot = _entry(client)
    feed["changes"]["vertretung"] = [_vertretung(_monday(), start="12:45")]
    monkeypatch.setattr(notifier, "is_poll_time", lambda now: True)
    notifier.tick(client.app.state.db_path, _at(_monday(), slot["startTime"], BEFORE_5))
    assert {s["title"] for s in sent} == {"8a Deutsch in 5 Min.", "Vertretung: DE (9a)"}


def test_scheduler_starts_and_stops(client):
    s = notifier.Scheduler(client.app.state.db_path)
    s.start()
    s.stop()
    assert not s._thread.is_alive()
