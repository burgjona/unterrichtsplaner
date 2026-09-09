# Konzept: Notenmodul

Fallback-Notenverwaltung neben dem Schulmanager. Setzt auf den vorhandenen Klassen
(`classes`, trägt bereits Fach, Klassenstufe und Schuljahr) und Schülerlisten
(`students`) auf.

Stand: bestätigt durch den Projektleiter. Offene Punkte sind als solche markiert.

## 1. Grundidee: Leistung (Spalte) und Note (Zelle)

Noten werden nicht lose gesammelt, sondern hängen an einer **Leistung** – dem Anlass, aus
dem sie entstanden ist (z. B. „Klassenarbeit Balladen, 14.11.2025, große Note"). Unter der
Leistung liegen die **Noten** der einzelnen Schüler.

Daraus ergibt sich die Notenmatrix von selbst, und sowohl Durchschnitt als auch alle vier
Word-Exporte lesen dieselbe Struktur. Eine Note für nur einen einzelnen Schüler bleibt
möglich: eine Leistung mit genau einer gefüllten Zelle.

## 2. Datenmodell (Migration `067_noten.sql`)

### `grade_items` – die Leistung / der Anlass

| Spalte | Bedeutung |
| --- | --- |
| `user_id`, `class_id` | Nutzer-Scoping, Zugehörigkeit zur Klasse (CASCADE) |
| `title` | Freitext, z. B. „Balladen: Der Erlkönig" |
| `kind` | Anlass, einer von acht (siehe unten) |
| `size` | `gross` oder `klein` |
| `date` | Datum der Leistung (ISO in der DB, TT.MM.JJJJ in der UI) |
| `term` | `HJ1` / `HJ2`, beim Anlegen frei wählbar, vorbelegt aus dem Datum |
| `note` | Freifeld „weitere Hinweise" zur Leistung |
| `lesson_id` | optionale Verknüpfung zur Unterrichtsstunde |

**Anlässe (`kind`)**: Leistungskontrolle · Komplexe Leistung · Klassenarbeit · Referat ·
Präsentation · mündliche Leistung · Hausaufgabe · Stundenleistung

### `grades` – die Notenzelle

`item_id`, `student_id`, `value` (REAL, darf NULL sein), `comment` (Freifeld „weitere
Hinweise" zur einzelnen Note). Eindeutig je (Leistung, Schüler).

Bewusst **ohne Status-Feld**: eine fehlende Leistung bleibt einfach leer und zählt nicht in
den Durchschnitt. Wenn ein Grund festgehalten werden soll, steht dafür das Hinweisfeld
bereit.

### `term_grades` – die Zeugnisnote

`class_id`, `student_id`, `term`, `value`, `comment`. Wird nur angelegt, wenn die Note von
Hand gesetzt wird; sonst zeigt die Ansicht den berechneten Vorschlag.

Alle drei Tabellen sind nutzer-gescopt, haben `sync_log`-Trigger (offline-fähig wie jede
andere Entität) und hängen per `ON DELETE CASCADE` an Klasse bzw. Schüler.

## 3. Notenwerte mit Tendenz

Gespeichert wird eine Dezimalzahl, die Tendenz ist ein Viertelschritt:

| Eingabe | `1+` | `1` | `1-` | `2+` | `2` | `2-` | … | `6` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Wert | 0,75 | 1,0 | 1,25 | 1,75 | 2,0 | 2,25 | … | 6,0 |

Die Eingabe akzeptiert `2`, `2+`, `2-`, `2,5` und `2.5`; angezeigt wird die Tendenzform,
sofern der Wert auf dem Raster liegt, sonst die Dezimalzahl mit Komma. Gültiger Bereich:
0,75 bis 6,0 (`6-` gibt es nicht).

Durchschnitte werden auf zwei Nachkommastellen gerundet ausgegeben.

## 4. Gewichtung

Eine Einstellung **pro Klasse** – da eine Klasse bereits Fach und Schuljahr trägt, ist das
zugleich „je Klasse und Fach pro Schuljahr einmal". Neue Spalte an `classes`:
`noten_gross_anteil` (Prozent, Standard 50).

Gerechnet wird in zwei Töpfen:

```
Ø groß   = Mittel aller großen Noten
Ø klein  = Mittel aller kleinen Noten
Ø gesamt = (Ø groß × anteil + Ø klein × (100 − anteil)) / 100
```

Ist einer der beiden Töpfe leer, zählt der andere allein – dieser Sonderfall braucht keine
Einstellung und taucht in der Oberfläche nicht auf. Einzelne Leistungen können **nicht**
abweichend gewichtet werden; das war die ausdrückliche Entscheidung gegen Klickarbeit.

Ein zusätzlicher Rundungsschalter ist bewusst entfallen: die Zeugnisnote wird ohnehin von
Hand gesetzt (siehe unten), damit hätte er keine Wirkung.

## 5. Zeugnisnote

Das System schlägt die kaufmännisch gerundete Ganznote aus `Ø gesamt` vor. Die endgültige
Note setzt der Lehrer; weicht sie vom Vorschlag ab, wird das in der Ansicht sichtbar
markiert und kann im Kommentarfeld begründet werden.

**Grenzfälle** – liegt `Ø gesamt` genau zwischen zwei Ganznoten (2,50 / 3,50 …), gibt es
keinen Vorschlag, sondern beide Möglichkeiten: „2 oder 3", dazu eine Markierung in der
Zeugnisnoten-Liste. Dort entscheidet der Lehrer je Schüler; eine Rundungsregel würde eine
Genauigkeit vortäuschen, die der Durchschnitt nicht hergibt. Die Markierung verschwindet,
sobald eine Note gesetzt ist.

Aus demselben Grund zählt der **Notenspiegel** im Word-Export solche Halbwerte keinem
Balken zu, sondern weist sie unter der Tabelle gesondert aus; die Prozentanteile beziehen
sich dann auf die übrigen Noten. In Durchschnitt und in die Zahl der bewerteten Arbeiten
gehen sie normal ein.

## 6. Oberfläche

**Hauptmenüpunkt „Noten"** mit Klassen- und Halbjahresauswahl:

1. **Notenmatrix** – Schüler × Leistungen, Spalten nach Datum sortiert, rechts die Spalten
   Ø groß / Ø klein / Ø gesamt. Zellen direkt editierbar, Navigation per Tab und
   Pfeiltasten.
2. **Schnellerfassung** – eine Leistung, Klassenliste untereinander, Ziffer + Enter.
3. **Schülerblatt** – alle Noten eines Schülers chronologisch mit Anlass, Datum und
   Hinweisfeld.

Dazu eine kompakte **Notenkachel im Klassendetail**, die in die Hauptansicht verlinkt.

Mobil ausschließlich über `@media`-Blöcke; die Matrix scrollt horizontal in ihrem eigenen
`overflow-x`-Container, die Seite selbst nie.

## 7. Word-Export

`src/lib/noten_export.py` auf python-docx (bereits Dependency, vgl. `asuv_export.py`), vier
Vorlagen:

1. **Notenmatrix der Klasse** – Querformat, Schüler × Leistungen mit Ø-Spalten
2. **Einzelblatt je Schüler** – eine Seite pro Schüler, Noten chronologisch
3. **Auswertung einer Leistung** – Notenverteilung, Durchschnitt, Schülerliste
4. **Zeugnisnoten-Liste** – kompakt Schüler → Endnote je Halbjahr

Datumsformat durchgängig TT.MM.JJJJ, Umlaute erhalten, Download-Header mit ASCII-Fallback
und RFC-5987 `filename*`.

## 8. Meilensteine

| # | Inhalt |
| --- | --- |
| 1 | Migration, Rechenkern (`src/lib/noten.py`), API, Tests |
| 2 | Ansicht „Noten": Matrix + Schnellerfassung |
| 3 | Word-Export, alle vier Vorlagen |
| 4 | Schülerblatt, Zeugnisnoten, Klassendetail-Kachel, Mobile-Feinschliff |
