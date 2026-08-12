-- Notizenfeld je Kalendereintrag + Mehrfachauswahl Klassen für manuell angelegte Termine.
-- class_id bleibt für auto-generierte Stundentermine (immer genau eine Klasse) bestehen.

ALTER TABLE calendar_entries ADD COLUMN notes TEXT;

CREATE TABLE calendar_entry_classes (
  entry_id INTEGER NOT NULL REFERENCES calendar_entries(id) ON DELETE CASCADE,
  class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  PRIMARY KEY (entry_id, class_id)
);
CREATE INDEX idx_cal_entry_classes_class ON calendar_entry_classes(class_id);
