-- "Tafelbild vorschlagen": KI erstellt aus einem Freitext ein strukturiertes Tafelbild
-- (Titel + frei viele Blöcke aus Überschrift/Stichpunkten, optional als Merksatz
-- hervorgehoben) - Blockanzahl/-gliederung entscheidet die KI frei, keine feste Vorgabe.
-- tafelbild_json speichert {"titel": "...", "bloecke": [{"ueberschrift": "...",
-- "punkte": [...], "hervorgehoben": bool}, ...]}, gerendert im Bearbeitungsfenster der
-- Unterrichtsplanung. tafelbild_notiz ist ein separates Freitextfeld für eigene
-- Ergänzungen der Lehrkraft (kein KI-Inhalt).

ALTER TABLE lessons ADD COLUMN tafelbild_eingabe TEXT;
ALTER TABLE lessons ADD COLUMN tafelbild_json TEXT;
ALTER TABLE lessons ADD COLUMN tafelbild_notiz TEXT;
