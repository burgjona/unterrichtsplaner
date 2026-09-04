-- Textformatierung (fett/kursiv/unterstrichen/Farbe) fuer die beiden Freitextfelder, die
-- die Lehrkraft selbst tippt: die Notiz zum Tafelbild und den Heftereintrag der SuS.
--
-- Bewusst je eine ZUSAETZLICHE Spalte statt HTML in der bestehenden: tafelbild_notiz und
-- hefteintrag behalten den reinen Text. Damit bleibt der Volltextindex sauber (058 indiziert
-- hefteintrag — HTML-Tags wuerden dort als eigene Tokens landen), aeltere/Offline-Clients
-- lesen weiter ein sinnvolles Feld, und Altbestaende koennen nicht durch ein misslungenes
-- Maskieren beschaedigt werden.
--
-- Quelle der Wahrheit ist die *_html-Spalte, sobald sie gefuellt ist; der Klartext daneben
-- wird serverseitig daraus abgeleitet (src/lib/richtext.py), damit beide nie auseinanderlaufen.
-- Kein Backfill noetig: NULL in *_html heisst "unformatiert" und faellt auf den Klartext zurueck.

ALTER TABLE lessons ADD COLUMN tafelbild_notiz_html TEXT;
ALTER TABLE lessons ADD COLUMN hefteintrag_html TEXT;
