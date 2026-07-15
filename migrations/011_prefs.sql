-- Meilenstein 12 – U9: Darstellungs-Einstellungen (Jahreszeit-Theme, Hell/Dunkel, Schriftart)
-- SQLite-ALTER kennt kein CHECK auf Bestandsspalten → Validierung erfolgt app-seitig
-- (theme ∈ {fruehling,sommer,herbst,winter}, font ∈ {verspielt,standard}, dark_mode ∈ {0,1}).

ALTER TABLE user_settings ADD COLUMN theme TEXT NOT NULL DEFAULT 'fruehling';
ALTER TABLE user_settings ADD COLUMN dark_mode INTEGER NOT NULL DEFAULT 0;
ALTER TABLE user_settings ADD COLUMN font TEXT NOT NULL DEFAULT 'verspielt';
