-- U18: Sitzplan je Klasse. Ein Sitzplan gehört einer Klasse (CASCADE beim Hard-Delete
-- der Klasse) und einem Nutzer (nutzergescopte Abfragen). layout_json kodiert die
-- Platzanordnung als JSON: {"seats": [{"row":0,"col":0,"studentId":12,"name":"Anna"}, ...]}.
-- rows/cols sind die Rasterdimension (redundant zum Layout, aber praktisch fürs Rendern).

CREATE TABLE seat_plans (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  class_id    INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  rows        INTEGER,
  cols        INTEGER,
  layout_json TEXT NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_seat_plans_class ON seat_plans(class_id);
CREATE INDEX idx_seat_plans_user  ON seat_plans(user_id);
