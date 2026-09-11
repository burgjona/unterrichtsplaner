-- U29: Sicherungspasswort. Verschlüsselt die Datensicherung (AES-256-ZIP, Download und
-- nächtlicher Lauf) und die Word-Exporte des Notenmoduls – für den Fall, dass eine dieser
-- Dateien im Download-Ordner, in der iCloud oder auf einem fremden Rechner liegen bleibt.
--
-- Abgelegt wie der Anthropic-Key: AES-256-GCM mit APP_SECRET_KEY, nie im Klartext. Der
-- Server muss es selbst entschlüsseln können, weil die nächtliche Sicherung ohne Anmeldung
-- läuft (src/backup_cli.py).

ALTER TABLE user_settings ADD COLUMN backup_pw_cipher BLOB;   -- verschlüsseltes Passwort
ALTER TABLE user_settings ADD COLUMN backup_pw_nonce  BLOB;   -- AES-GCM-Nonce
ALTER TABLE user_settings ADD COLUMN backup_pw_set_at TEXT;   -- Zeitpunkt der Festlegung
