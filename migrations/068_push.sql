-- Web-Push-Benachrichtigungen (M1): VAPID-Schlüssel des Servers + Geräte-Anmeldungen.
--
-- Push läuft über die Push-Dienste der Browser (Apple/Google/Mozilla); der Server
-- authentifiziert sich dort mit einem eigenen VAPID-Schlüsselpaar (P-256). Das Paar wird
-- beim ersten Gebrauch erzeugt und bleibt danach stabil – ändert es sich, sind alle
-- bestehenden Geräte-Anmeldungen wertlos. Der private Teil liegt wie die übrigen
-- Geheimnisse AES-256-GCM-verschlüsselt (APP_SECRET_KEY) in der DB, nie im Klartext.

CREATE TABLE push_vapid (
    id              INTEGER PRIMARY KEY CHECK (id = 1),   -- genau eine Zeile (serverweit)
    public_key      TEXT NOT NULL,   -- base64url, unkomprimierter P-256-Punkt; geht an den Browser
    private_cipher  BLOB NOT NULL,   -- privater Schlüssel (PEM), verschlüsselt
    private_nonce   BLOB NOT NULL,   -- AES-GCM-Nonce
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Eine Zeile je Gerät/Browser (PushSubscription). endpoint ist die vom Push-Dienst
-- vergebene, gerätespezifische URL; p256dh/auth sind die Schlüssel zum Verschlüsseln
-- der Nachricht für genau dieses Gerät.
CREATE TABLE push_subscriptions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint         TEXT NOT NULL UNIQUE,
    p256dh           TEXT NOT NULL,
    auth             TEXT NOT NULL,
    label            TEXT,            -- Anzeige, z. B. "iPhone" / "Mac"
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    last_success_at  TEXT             -- letzte erfolgreiche Zustellung an den Push-Dienst
);

CREATE INDEX idx_push_subscriptions_user ON push_subscriptions(user_id);
