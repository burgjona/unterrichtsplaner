# Entwicklungsauftrag: Lehrer-Dashboard
**Referendariat Oberschule Stolpen, Sachsen | Fächer Deutsch & WTH**
**Stand: 03. Juli 2026 – Version 1.0 (final vor Entwicklungsstart)**

---

## 0. Arbeitsweise (verbindlich, vor jeder Codezeile lesen)

Du arbeitest an diesem Projekt wie ein Senior-/Enterprise-Entwickler: systematisch, nachvollziehbar, kosteneffizient und ohne Spekulation.

**Grundregeln:**
1. **Stoppen bei Unklarheit.** Sobald eine Anforderung mehrdeutig ist, eine Entscheidung fehlt oder ein technischer Trade-off getroffen werden muss, der nicht explizit in diesem Dokument steht: Arbeit unterbrechen, konkrete Frage stellen, auf Antwort warten. Keine Annahmen treffen und weitercoden "auf Verdacht".
2. **Keine Sackgassen.** Vor größeren strukturellen Entscheidungen (Datenmodell, Ordnerstruktur, Architektur-Pattern) kurz die geplante Lösung in 2–3 Sätzen zur Bestätigung vorlegen, bevor die Umsetzung beginnt – nicht erst nach Fertigstellung.
3. **Token-/Kosteneffizienz beim Entwickeln selbst.** Kein unnötiges Wiederholen bereits bekannter Datei-Inhalte, kein Neuschreiben ganzer Dateien wenn ein gezielter Patch reicht, keine redundanten Erklärungen im Code (Code soll selbsterklärend sein, Kommentare nur wo Logik nicht offensichtlich ist).
4. **Kleine, abgeschlossene Arbeitsschritte.** Jeder Abschnitt aus Kapitel 2 (Umsetzungsreihenfolge) ist ein eigener, testbarer Meilenstein. Nach jedem Abschnitt: kurzer Stand, was funktioniert, was noch fehlt, bevor der nächste Abschnitt begonnen wird.
5. **Keine Feature-Erfindung.** Nur umsetzen, was in diesem Dokument steht. Wenn dir während der Entwicklung ein sinnvolles Zusatzfeature einfällt: vorschlagen, nicht einfach bauen.
6. **Konsistenz vor Tempo.** Lieber eine Rückfrage zu viel als eine falsche Grundannahme, die später mehrere Bereiche betrifft (z. B. Datenmodell-Änderungen sind teuer, wenn schon viel darauf aufbaut).

---

## 1. Technische Grundarchitektur

| Bereich | Festlegung |
|---|---|
| Hosting | Synology DS723+, Docker (Container Manager) |
| Externer Zugriff | Cloudflare Tunnel (kostenlos) + eigene Domain, HTTPS |
| Backend | Eigenes Backend + **SQLite**-Datenbank (kein localStorage mehr) |
| Nutzerverwaltung | Echtes Login: Passwort-Hashing (z. B. bcrypt/argon2) + sicheres Session-Handling. Aktuell 1 Nutzer, Architektur aber von Anfang an mehrbenutzerfähig anlegen (keine hartkodierten Single-User-Annahmen im Datenmodell) |
| Dateispeicher | Echter Datei-Upload auf die NAS, keine reine Link-Ablage. Ordnerstruktur: **Fach / Klasse / Schuljahr** – vom System automatisch vorgegeben, nicht manuell vom Nutzer gepflegt |
| KI-Schicht | Anthropic Claude API, Modell-Routing nach Aufgabenkomplexität (siehe Kapitel 5) |
| Datenbasis Lehrplan | `lp_os_deutsch_2019.md` und `lp_os_wth_2019.md` (bereits vorhandene, aus PDF generierte Markdown-Dateien) – direkt als strukturierte Grundlage nutzen, PDFs nicht erneut parsen |
| Schultermine | Eigene MD-Datei (Format/Struktur mit Nutzer abstimmen, bevor der Parser gebaut wird), da Termine noch nicht feststehen |
| Ferien/Feiertage Sachsen | Automatischer Abruf beim Anlegen eines neuen Schuljahres über eine öffentliche kostenlose API (z. B. feiertage-api.de für Feiertage, ferien-api.de für Schulferien, jeweils Bundesland-Code SN), Ergebnis wird lokal in SQLite gespeichert (kein Live-Abruf bei jedem Kalenderaufruf) |
| Schulverwaltung | Kein Integration zu Schulmanager – rein manuelle Erfassung im Dashboard |
| Materialerstellung | Kein KI-Content-Erstellung – Turory bleibt externes Tool, Dashboard ist nur Ablage/Verknüpfung |
| Notenmodul | **Entfällt komplett** – nicht Teil des Funktionsumfangs |

---

## 2. Empfohlene Umsetzungsreihenfolge (Meilensteine)

Jeder Meilenstein wird erst begonnen, wenn der vorherige funktionsfähig und vom Nutzer kurz bestätigt ist.

### Meilenstein 1 – Datenmodell & Backend-Grundgerüst
- SQLite-Schema: Nutzer, Klassen (flexibel anlegbar/änderbar, keine feste Struktur), Schuljahre, Lernbereiche, Stunden, Kalendereinträge, Materialien, Verknüpfungstabellen (Material↔Stunde, Material↔Lernbereich)
- Klassen müssen während des Schuljahres jederzeit angelegt, geändert oder entfernt werden können, ohne bestehende Planungsdaten zu invalidieren
- **Rückfrage-Trigger:** Vor Festlegung des finalen Schemas kurz zur Bestätigung vorlegen

### Meilenstein 2 – Nutzerverwaltung & Login
- Registrierung/Login, Passwort-Hashing, Session-Cookies
- Mehrbenutzerfähig konzipiert, aber mit genau einem Account befüllt
- Einstellungsseite mit API-Key-Eingabefeld (siehe Kapitel 6)

### Meilenstein 3 – Kernfunktionen migrieren
- Klassen-, Stunden- und Reflexionsverwaltung aus dem bestehenden HTML/JS-Prototyp (`dash_v15.html`) 1:1 übernehmen, aber gegen SQLite statt localStorage
- Klafki-Analyse, Meyer-Ampel, Phasentabelle wie im Prototyp
- **Keine Testdaten migrieren** – kompletter Neustart der Dateninhalte

### Meilenstein 4 – Kalender-Automatik & Jahresplanung
- Jede gespeicherte Stunde erzeugt automatisch einen Kalendereintrag
- KI-gestützte Verplanung aller Lernbereiche auf das Schuljahr (Monats- und Wochenansicht), Grundlage: Stundenrichtwerte + Wochenstundenzahl + Ferien/Feiertage + fixe Termine
- Bei Konflikt mit bereits fix eingetragenem Termin: aktive Rückfrage an den Nutzer, ob der Termin verschiebbar ist oder wirklich fix bleibt
- Vollständig manuell nachjustierbar (Verschieben, Tauschen, Umbenennen)

### Meilenstein 5 – Materialbibliothek
- Echter Datei-Upload in die NAS-Ordnerstruktur (Fach/Klasse/Schuljahr)
- Pro Datei optionales zusätzliches Link-Feld (z. B. für Turory-Dokumente)
- Mehrfachverknüpfung: eine Datei kann mehreren Stunden und Lernbereichen zugeordnet werden
- **LaSuB-Begleitmaterialien (z. B. zu Lektüren) als KI-Wissensgrundlage:** Beim Upload wird der PDF-Text automatisch extrahiert und in Abschnitte zerlegt (Kapitel/Überschriften oder ca. 500–800 Wörter je Abschnitt), inkl. Referenz auf Ursprungsdatei und Seitenzahl. Diese Zerlegung ist reine Textverarbeitung, läuft nicht über die Sprach-KI und verursacht keine nennenswerten Zusatzkosten.
- **Gezielter Abruf statt Volltext-Übergabe:** Bei einer KI-Anfrage zu einer Stunde/einem Lernbereich sucht das System anhand von Fach/Klasse/Thema die 2–4 relevantesten Textabschnitte aus verknüpften Begleitmaterialien heraus (SQLite-Volltextsuche, `FTS5`) und übergibt nur diese an die KI – nie das komplette Dokument. Das hält Anfragen klein und die Kosten aus Kapitel 5 im Rahmen, auch bei umfangreichen PDFs.
- Semantische Suche (Embeddings) ist als spätere Erweiterung denkbar, falls Stichwortsuche zu ungenau trifft – nicht Teil des ersten Umsetzungsschritts, keine vorzeitige Komplexität einbauen.
- **Direkt-Upload aus Stoffverteilungsplan und Einzelstundenplanung:** Zusätzlich zum zentralen Upload in der Materialbibliothek muss ein Datei-Upload auch direkt im jeweiligen Dialog (Stoffverteilungsplan bzw. Unterrichtsstunde) möglich sein, ohne den Dialog zu verlassen. Technisch ruft dieser Upload denselben Speicher- und Indizierungspfad wie in der Materialbibliothek auf (gleiche NAS-Ordnerstruktur Fach/Klasse/Schuljahr, gleiche automatische Textextraktion) – es entsteht kein separater Datenpfad, nur ein zusätzlicher Eingabepunkt. Die Datei erscheint anschließend ganz normal auch in der zentralen Materialbibliothek und ist automatisch mit der Stunde bzw. dem Lernbereich verknüpft, aus dem sie hochgeladen wurde.

### Meilenstein 6 – ASUV-Modul & Export
- Automatische Vorbefüllung aus Klafki/Meyer/Phasentabelle nach der in Kapitel 4 hinterlegten Struktur
- Lehrbuch-Referenz (BiBox) bleibt manuelles Freitextfeld, System zeigt Erinnerungs-Hinweis, wenn das Feld bei einer geplanten Stunde noch leer ist (nicht blockierend)
- Export als PDF/Word mit bindenden Formatvorgaben (siehe Kapitel 4.2)

### Meilenstein 7 – Claude-API-Integration
- Echte Anbindung statt Simulation, Modell-Routing nach Kapitel 5
- Kostenanzeige in den Einstellungen (siehe Kapitel 6)

### Meilenstein 8 – Mobile-Feinschliff & QA
- Vollständige Prüfung aller Detailseiten (nicht nur Startseite) gegen die Breakpoints aus Kapitel 7
- Regressionstest: Desktop-Ansicht darf durch keine Mobile-Anpassung verändert werden

### Meilenstein 9 – Deployment
- Docker-Container auf der Synology, Cloudflare Tunnel + Domain, HTTPS-Test
- Wird gemeinsam mit dem Nutzer Schritt für Schritt durchgeführt, nicht vollständig autonom

---

## 3. Design-Referenz

- Bestehender HTML/CSS/JS-Prototyp `dash_v15.html` ist die verbindliche visuelle und interaktive Referenz (Farbpalette Frühlingsgrün/Gelb/Orange, Kartenlayout, Sidebar-Navigation, Kalenderansicht). Layout, CSS, Farbpalette, Textstrukturen und Button-Beschriftungen (inkl. ✨-Kennzeichnung) sind bindend – das eingebettete JavaScript ist reiner simulierter Prototyp-Code (z. B. `alert()`-Simulationen, `localStorage`) und wird vollständig durch die echte Backend-/SQLite-Anbindung ersetzt, nicht übernommen.
- Schriftart: `'Noteworthy Light', 'Noteworthy', 'Comic Sans MS'` mit Fallback-Kette für Browser ohne native Unterstützung
- Alle Umlaute (ä, ö, ü) und ß korrekt verwenden – keine Transliteration (ae/oe/ue) in UI-Texten, Datenbankfeldern oder Exporten
- Sidebar-Kopfbereich zeigt aktuellen Wochentag + Tag/Monat (ohne Jahr), keinen separaten Titel/Untertitel mehr
- Vier KPI-Cards auf der Übersichtsseite sind klickbare Links zu ihren Detailseiten
- KI-generierende Buttons erhalten das Präfix **✨** vor dem Button-Text (visuelle Konvention, um KI-Aktionen von normalen Aktionen zu unterscheiden)

---

## 4. Didaktische Fachlogik (bindend)

### 4.1 Planungsebenen
- **Stoffverteilungsplan** (Jahresebene): pro Fach/Klasse/Schuljahr, Parallelklassen mit gemeinsamem Inhalt aber getrennten Terminschienen, Pflicht-Übungsstunde vor jeder Leistungsüberprüfung (flexibel einstellbar), Puffer-Stunden planbar
- **Sequenz-/Wochenplanung**: verknüpft Lernbereich mit mehreren Einzelstunden
- **Einzelstunde**: Klafki (5 Grundfragen) → Meyer-Checkliste (Ampel) → Phasentabelle (Zeit, Sozialform, Methode, Lehrer-/Schülertätigkeit, Material, Differenzierung G/M/E) → Ressourcenplanung (Beamer/iPad/Computerraum/Werkstatt/Küche), Workflow ist Pflicht aber manuell überspringbar

### 4.2 ASUV-Struktur (verbindlich, Quelle: LASUB-Handreichung)
1. Bedingungsanalyse (organisatorisch/technisch, Lernvoraussetzungen, Einordnung in Lernbereich)
2. Lehr- und Lernziele
3. Sachanalyse
4. Didaktische Analyse und methodische Entscheidungen (inkl. didaktische Reduktion, getrennt von Methodik)
5. Verlaufsplanung
6. Anhang

Format: Arial 11, Zeilenabstand 1,5, Blocksatz, ca. 15 Seiten Textkörper, Deckblatt + Inhaltsverzeichnis + normgerechte Quellenangaben + Selbständigkeitserklärung. Konsistenzprüfung zwingend: Faktoren aus Kapitel 1 müssen in Kapitel 4 wieder aufgegriffen werden, sonst streichen.

### 4.3 Qualitätsprinzipien
- Meyer: 10 Merkmale guten Unterrichts als Planungscheckliste und Reflexionsraster (Ampel), stundentyp-abhängig gewichtet
- Dreifachdifferenzierung G/M/E pro Phase
- Handlungs-/Problemorientierung: WTH Pflichtfeld mit Kompetenzfeld-Bezug, Deutsch aktive KI-Erinnerung bei mehreren Stunden ohne Handlungsanlass
- Sozialform-Monotonie-Warnung über mehrere Stunden hinweg

---

## 5. KI-Integration: Wo und mit welchem Modell

**Leitprinzip:** KI liefert ausschließlich Vorschläge/Erstentwürfe, niemals finale unveränderliche Ausgaben. Jedes KI-Feld bleibt normal editierbar. Keine automatische Speicherung ohne expliziten Nutzer-Klick.

| Funktion | Modell | Begründung |
|---|---|---|
| Methodenvorschlag (Ressourcen/Differenzierung) | Claude Haiku | Häufig, strukturiert, geringer Kontextbedarf |
| Ressourcenwarnung (Technik ohne Raumbuchung) | Claude Haiku | Reine Logikprüfung |
| Sozialform-Monotonie-Check | Claude Haiku | Mustererkennung über wenige Datenpunkte |
| Meyer-Ampel-Erstvorschlag | Claude Haiku | Kurze schematische Einschätzung |
| Klafki-Erstentwurf (5 Grundfragen) | Claude Sonnet | Erfordert didaktisches Verständnis |
| Lernbereichs-Sequenzierung (Kalender) | Claude Sonnet | Mittlere Komplexität, mehrere Stunden sinnvoll ordnen |
| Stoffverteilungsplan-Generierung (Jahresebene) | Claude Sonnet | Muss Lehrplanstruktur, Zeitlogik, andere Lernbereiche, Aktualität/Alltagsrelevanz kombinieren |
| ASUV-Ausformulierung | Claude Sonnet | Höchste Textqualität/Konsistenz nötig, Notenrelevanz |

**Implementierungsregel:** Modellwahl ist pro Funktion im Backend fest hinterlegt, nicht dynamisch/zufällig gewählt.

**Einbindung von LaSuB-Begleitmaterialien:** Klafki-Erstentwurf, Lernbereichs-Sequenzierung und Stoffverteilungsplan-Generierung beziehen zusätzlich zum Lehrplan automatisch passende Textauszüge aus verknüpften Begleitmaterialien ein (z. B. LaSuB-Material zu einer Lektüre), sofern für Fach/Klasse/Thema vorhanden – siehe Meilenstein 5, gezielter Abruf statt Volltext-Übergabe.

**Reaktion auf Ausfall/Planänderung:** Verschiebt sich ein Lernbereich (z. B. durch Unterrichtsausfall), passt die KI nachfolgende Lernbereiche automatisch an und markiert die Änderung sichtbar. Parallelklassen laufen bei Ausfall eigenständig weiter, Divergenz wird angezeigt.

---

## 6. Einstellungen: API-Key & Kostentransparenz

- Eingabefeld für Anthropic API-Key in den Einstellungen
- Statusanzeige: "API-Key aktiv" / "Kein API-Key hinterlegt" (mit klarem visuellem Zustand, z. B. grüner/roter Indikator)
- Solange kein Key hinterlegt ist: alle KI-Funktionen im UI erkennbar deaktiviert, keine Fehlermeldungen bei Klick, sondern Hinweis auf fehlenden Key
- Kostenübersicht: monatliche Aggregation der Token-Nutzung pro Modell, grobe Kostenschätzung in Euro/Dollar, keine Echtzeit-Cent-Genauigkeit nötig
- Referenzgröße für Nutzer: bei normaler Nutzungsintensität ca. 2–3 USD/Monat zu erwarten (Haiku-dominiert, Opus nur für ASUV)

---

## 7. Mobile-Anforderungen (verbindliche Abnahmekriterien)

Diese Punkte sind technisch eindeutig zu prüfen, nicht nur als "soll mobil gut funktionieren" zu verstehen:

1. **Kein horizontaler Scrollbalken auf Seitenebene**, bei keiner Bildschirmbreite. `overflow-x:hidden` auf `html`/`body` als Sicherheitsnetz, aber Ursache (zu breite Elemente) muss trotzdem behoben werden, nicht nur überdeckt.
2. **Alle mobilspezifischen CSS-Regeln strikt innerhalb von `@media`-Blöcken.** Niemals globale Regeln einführen, die versehentlich auch den Desktop verändern. Vor jedem CSS-Commit: Diff-Check, ob Desktop-Ausgabe unverändert bleibt.
3. **Tabellen brechen um, statt zu scrollen** (`table-layout:fixed`, Wortumbruch in Zellen) – kein horizontales Wegscrollen von Tabelleninhalten.
4. **Navigation als Off-Canvas-Menü mit Burger-Button** unterhalb von 920px Breite, mit Backdrop-Overlay und automatischem Schließen bei Auswahl. Burger-Button sitzt inline in der Kopfzeile neben dem Seitentitel, nicht als überlagerndes Fixed-Element.
5. **Touch-Ziele mindestens 44×44px**, Eingabefelder mit Schriftgröße 16px (verhindert iOS-Auto-Zoom) – ausschließlich innerhalb der Mobile-Media-Query.
6. **Verbindliche Breakpoints:** 1080px (Mehrspalten-Grids werden einspaltig), 920px (Sidebar wird Off-Canvas), 600px (Feinschliff Abstände/Schriftgrößen).
7. **Jede Detailseite einzeln testen**, nicht nur die Startseite – insbesondere Kalender, Stundenplanung, ASUV-Formular, Materialbibliothek.

---

## 8. Offene Punkte, die während der Entwicklung mit dem Nutzer zu klären sind

Diese Punkte sind bewusst nicht vorab entschieden und erfordern eine Rückfrage, sobald der jeweilige Meilenstein erreicht wird:

1. **Format/Struktur der Schultermine-MD-Datei** – vor dem Bau des Parsers gemeinsam festlegen
2. **Feinschliff des Prompt-Designs** für die KI-Funktionen aus Kapitel 5 (konkrete System-Prompts) – iterativ mit dem Nutzer abstimmen, nicht einmalig festschreiben
3. **API-Key-Beschaffung und Docker/Cloudflare-Einrichtung** – wird gemeinsam Schritt für Schritt durchgeführt, nicht autonom von Claude Code vorweggenommen

---

## Zusammenfassung der Nicht-Ziele (explizit ausgeschlossen)

- Kein Notenmodul
- Keine Schulmanager-Integration
- Keine KI-gestützte Materialerstellung (bleibt bei Turory)
- Keine automatische Reflexionsjournal-Logik (rein manuell)
- Keine Migration bestehender Prototyp-Testdaten
