-- Web-Push M2: was bereits gemeldet wurde (Erinnerungen, Schulmanager-Änderungen).
--
-- Der Hintergrund-Takt prüft jede Minute bzw. alle 15 Minuten erneut; jede Meldung hat
-- einen stabilen Schlüssel (z. B. "erinnerung:2026-09-14:07:30:stunde"), der vor dem
-- Versand hier eingetragen wird – so geht jede Nachricht genau einmal raus, auch über
-- Neustarts hinweg. Alte Zeilen räumt der Takt nachts auf.

CREATE TABLE push_sent (
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key      TEXT NOT NULL,
    sent_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, key)
);
