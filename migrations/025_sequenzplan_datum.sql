-- Sequenzplan: voraussichtliches Datum je Sequenzstunde. Eigenständiges, jederzeit
-- leerbares Feld -- unabhängig vom Datum einer evtl. verknüpften lessons-Zeile.

ALTER TABLE sequenz_stunden ADD COLUMN date TEXT;
