-- Schulmanager-Online-Anbindung (M1a): geheimer ICS-Stundenplan-Link je Nutzer.
--
-- Kein Login, keine inoffizielle API: Schulmanager bietet einen personalisierten,
-- stündlich aktualisierten iCal-Feed unter /ical/schedules/<token> mit den eigenen
-- Unterrichtsstunden (regularLesson/specialLesson) und Aufsichten (supervision).
-- Der Link ist ein Geheimnis (wer ihn kennt, sieht den Stundenplan) und wird daher
-- wie der Google-Schlüssel AES-256-GCM-verschlüsselt abgelegt, nie im Klartext.

ALTER TABLE user_settings ADD COLUMN schulmanager_ical_cipher  BLOB;  -- verschlüsselte ICS-URL
ALTER TABLE user_settings ADD COLUMN schulmanager_ical_nonce   BLOB;  -- AES-GCM-Nonce
ALTER TABLE user_settings ADD COLUMN schulmanager_ical_set_at  TEXT;  -- ISO-Zeitpunkt der Hinterlegung
ALTER TABLE user_settings ADD COLUMN schulmanager_last_sync    TEXT;  -- ISO-Zeitpunkt des letzten Abrufs
