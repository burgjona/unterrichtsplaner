-- Doppelstunde aus der Unterrichtsplanung: 2 Sequenzstunden dürfen auf dieselbe lessons-Zeile
-- zeigen (bisher per UNIQUE INDEX hart auf 1:1 begrenzt). Die Obergrenze von 2 wird jetzt
-- ausschließlich im Router (sequenzplan.py::link) durchgesetzt.

DROP INDEX idx_sequenz_stunden_lesson_uniq;
CREATE INDEX idx_sequenz_stunden_lesson ON sequenz_stunden(lesson_id) WHERE lesson_id IS NOT NULL;
