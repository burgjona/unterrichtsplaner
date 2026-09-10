# Repository-Sichtbarkeit: Befund und Empfehlung

*Geprüft am 10.9.2026, ausgelöst durch die Frage beim Aufsetzen von Adlernest
(`burgjona/Adlernest`, das Familienportal auf derselben NAS).*

## Ausgangslage

`burgjona/unterrichtsplaner` ist **öffentlich**. Das ist beim Einrichten von
Adlernest aufgefallen: Der Container auf der NAS zieht aus diesem Repository
über HTTPS **ohne jede Anmeldung** — genau deshalb funktioniert es. Adlernest
ist privat und braucht deshalb einen eigenen Zugang.

## Was geprüft wurde

Vollständiger Klon, 217 Commits, 207 Dateien.

| Geprüft | Ergebnis |
|---|---|
| `.env`, Secret- oder Credential-Dateien je committet | **nein** |
| Token-Muster in der gesamten Historie (`ghp_`, `sk-`, `AIza`, JWT) | **keine** |
| Zugangsdaten im Code (`api_key`, `password`, `token` mit Literal) | **keine** — nur das Test-Fixture `alt-token` in `tests/test_auth.py` |
| Namensmuster in `src/seed.py` | **keine** |
| `src/routers/schulmanager.py` speichert Zugangsdaten im Code | **nein** |

**Es ist nichts ausgetreten.** Kein Handlungsdruck, keine Rotation nötig.

## Empfehlung: trotzdem auf privat stellen

Nicht wegen dem, was drin ist, sondern wegen des Verhältnisses. Es gibt keinen
Vorteil daraus, dass es öffentlich ist — keine Mitwirkenden, keine Nutzer, kein
Portfolio-Zweck. Dem stehen drei dauerhafte Nachteile gegenüber:

1. Der Code, der unter einer erreichbaren Adresse läuft (`schule.adlerstolpen.de`),
   liegt offen. Die Anmeldung ist solide gebaut (argon2, serverseitige Sitzungen),
   das ist also **kein akutes Risiko** — aber es gibt auch keinen Grund, sie herzugeben.
2. Eine **Schulmanager-Online-Integration** öffentlich zu dokumentieren, ist
   mindestens unelegant. Wie deren Nutzungsbedingungen dazu stehen, ist ungeprüft.
3. Der eigentliche Punkt: Solange es öffentlich ist, ist **jeder künftige Commit**
   eine Gelegenheit, versehentlich etwas hinauszugeben. Bei einer Schul-Anwendung
   mit Schüler:innen-Notizen ist das ein stehendes Risiko für null Gegenwert.

Gegenargument, der Fairness halber: Verbergen ist keine Sicherheit. Wer den Code
liest, findet nichts, was die Anwendung angreifbar macht. Das hier ist ein
„warum das Risiko tragen, wenn es nichts bringt"-Argument, keine Warnung.

## Was beim Umstellen zu beachten ist

**Der Pull auf der NAS bricht sofort.** `/volume1/docker/adlerplan` zieht heute
über HTTPS ohne Login — das geht nur, weil das Repository öffentlich ist. Nach
der Umstellung braucht es einen Zugang, und das Remote muss von HTTPS auf SSH
umgestellt werden (oder auf ein Token).

**Privat machen macht nichts ungeschehen.** Hier ohne Folgen, weil nichts drin
war. Als Regel gilt aber: Ein je committetes Geheimnis muss *gewechselt* werden,
nicht versteckt.

## Zugang für die NAS, wenn beide Repositories privat sind

Deploy-Keys gelten **je Repository** — GitHub lehnt denselben Schlüssel für ein
zweites ab. Für zwei private Repositories auf derselben Maschine also entweder:

- **zwei Deploy-Key-Paare** mit zwei `Host`-Einträgen in `/root/.ssh/config` —
  laufen nie ab, dafür zweimal derselbe Aufwand, oder
- **ein Fine-grained Token** mit Lesezugriff auf beide — einmal einrichten, beide
  Remotes bleiben auf HTTPS, dafür Ablaufdatum (höchstens ein Jahr).

Ab zwei privaten Repositories auf einer Maschine ist das Token die geringere Mühe.

## Vorgeschlagene Reihenfolge

1. Adlernest zuerst live bringen, mit Deploy-Key auf der NAS (läuft gerade).
2. Wenn der Weg dort steht: Unterrichtsplaner auf privat, Zugang einrichten,
   Remote umstellen. Dann ist der Ablauf schon bekannt.

Nichts davon eilt — der Unterrichtsplaner läuft.

---

# Nachtrag: Gegenprüfung und Umstellungsanleitung

*Ergänzt am 10.9.2026, unabhängige zweite Prüfung plus die konkrete Klickfolge
und die Skripte für die NAS.*

## Teil 1 — Gegenprüfung des Befundes

Zweiter, unabhängiger Durchgang: alle 1002 Blobs der Historie ausgepackt und im
Inhalt durchsucht, nicht nur der aktuelle Stand, nicht nur Dateinamen.

### Der Befund oben ist bestätigt

| Zusätzlich geprüft | Ergebnis |
|---|---|
| Personenbezogene Daten (Schüler:innen-Namen, Klassenlisten, Noten, Sitzpläne) | **keine** — alle Namen in Tests sind erfunden (Anna Müller, Ben Groß, Max Weiß, Bert Straßer) |
| `uploads/` und `storage/` in der Historie | enthalten **nur** `.gitkeep`; `.gitignore` sperrt `uploads/*` und `storage/*` korrekt |
| Datenbankdateien (`data.db`, `*.sqlite`) je committet | **nein**, auch nicht unter anderem Namen |
| Binärdateien / Anhänge | eine einzige: `tests/fixtures/sample.pdf`, 2 KB, von ReportLab erzeugtes Dummy |
| **Je committete und später gelöschte Dateien** | **keine — null.** Nichts wurde je hinzugefügt und wieder entfernt |
| E-Mail-Adressen in der Historie | 13 Stück, **alle** synthetisch (`ref@stolpen.de`, `a@b.de`, Schulmanager-Termin-IDs) |
| Private Keys | ein Treffer in `tests/test_google_cal.py` — Inhalt ist wörtlich `\nfake\n` |
| Token-Muster (breiter gefasst: `github_pat_`, `xox*`, `AKIA`, JWT, Cloudflare-Token) | **keine**, nur der Platzhalter `sk-ant-api03-EXAMPLE-1234` |
| IP-Adressen in Doku | nur RFC-5737-Dokumentations-IPs (`203.0.113.x`, `198.51.100.x`) — bewusst synthetisch |

Der Punkt mit den gelöschten Dateien ist der stärkste: In 217 Commits wurde
**nie** eine Datei entfernt. Damit gibt es auch keinen Kandidaten für ein
„war mal kurz drin". Der Befund oben steht.

### Drei Dinge, die im ersten Durchgang nicht benannt waren

Keines davon ist ein Leck. Alle drei sind Argumente, die die Empfehlung
verstärken — und eines ist ein konkreter Beinahe-Unfall.

**1. Das Repository benennt Person, Schule und Fächer.**
`README.md`, `CLAUDE.md` und `claude_code_briefing_lehrer_dashboard.md` sagen
wörtlich „Referendariat Oberschule Stolpen, Sachsen | Fächer Deutsch & WTH".
Zusammen mit dem GitHub-Konto ist damit öffentlich zuordenbar, *wer* an *welcher
Schule* diese Anwendung betreibt. Das ist für sich harmlos — es steht ja niemand
drin außer ihm selbst. Aber es verändert das Verhältnis: Ein anonymes Code-Repo
zu finden ist Zufall, ein namentlich zugeordnetes ist eine Adresse. Und wenn
irgendwann doch einmal etwas hineinrutscht, ist von der ersten Sekunde an klar,
zu wessen Schule es gehört.

**2. `DEPLOY.md` ist eine vollständige Betriebsanleitung der laufenden Instanz.**
Öffentlich dokumentiert sind: der Hostname der erreichbaren Instanz
(`schule.adlerstolpen.de`, im Befund oben), der Container-Port 8097, die
Volume-Namen, die Backup-Pfade unter `/volume1/Backups/`, der Cloudflare-Tunnel-
Aufbau und der Hinweis, dass `APP_SECRET_KEY` den gespeicherten Anthropic-Key
entschlüsselt. Nichts davon ist ein Geheimnis im engeren Sinn. Aber es ist eine
Landkarte des Systems, das unter einer öffentlich erreichbaren Adresse läuft,
und die gibt man ohne Gegenwert nicht her.

**3. Konkreter Beinahe-Unfall: eine ungetrackte PDF liegt im Projektordner.**
Im Arbeitsverzeichnis liegt `lp_os_musik_2019.pdf` (486 KB), ungetrackt — und
`.gitignore` fängt sie **nicht** ab (`git check-ignore` liefert nichts). Ein
einziges `git add -A` würde sie in ein öffentliches Repository committen.
Inhaltlich ist es der sächsische Musik-Lehrplan, also kein Schaden. Aber genau
dieser Mechanismus ist das Risiko, das oben unter Punkt 3 beschrieben ist — hier
in freier Wildbahn, im aktuellen Arbeitsverzeichnis, heute.

*Empfehlung dazu, unabhängig von der Sichtbarkeit:* entweder die Datei nach
`docs/` verschieben und bewusst committen (Lehrpläne sind amtliche Dokumente,
`docs/lp_os_deutsch_2019.md` und `docs/lp_os_wth_2019.md` liegen ohnehin schon
drin), oder `*.pdf` im Wurzelverzeichnis in `.gitignore` aufnehmen. Nicht liegen
lassen.

### Fazit der Gegenprüfung

Es ist nichts ausgetreten — das bleibt so. Es wurde nichts übersehen, was
Handlungsdruck erzeugt. Die drei Punkte oben verschieben die Empfehlung aber von
„könnte man" ein Stück in Richtung „sollte man bei Gelegenheit", und Punkt 3
sollte ohnehin heute noch aufgeräumt werden.

## Teil 2 — Welcher Zugang: zweiter Deploy-Key

Die Abwägung oben lässt beides offen und tendiert ab zwei Repositories zum
Token. Mit dem Betriebsalltag im Blick fällt sie hier zugunsten des **zweiten
Deploy-Key-Paars** aus, aus einem Grund, der oben noch nicht drinsteht:

**Der Ablauf des Tokens ist deshalb teuer, weil es keine Shell gibt.** Vom
Arbeitsmac kommt man nicht per SSH auf die NAS; jede Änderung läuft über ein
Skript im Aufgabenplaner. Ein Deploy-Key wird **einmal** eingerichtet und läuft
nie ab. Ein Fine-grained Token muss spätestens nach einem Jahr erneuert werden —
und zwar über genau denselben Aufgabenplaner-Umweg, dann für beide Repositories
gleichzeitig, an einem Tag, an dem man nicht damit rechnet und der Deploy
kommentarlos stehenbleibt. Der einmalige Mehraufwand des zweiten Schlüsselpaars
ist kleiner als eine wiederkehrende Pflicht, die man nur bemerkt, wenn sie
ausfällt.

Dazu kommt: Ein Deploy-Key mit Lesezugriff kann genau ein Repository lesen und
sonst nichts. Ein Token liegt zudem im Klartext in der Remote-URL oder in einer
Credential-Datei auf der NAS. Der Schlüssel liegt in `/root/.ssh/`, wo die
Adlernest-Variante schon liegt und wo das Berechtigungsmodell schon stimmt.

*Wenn irgendwann ein drittes und viertes privates Repository dazukommt, kippt die
Rechnung wieder Richtung Token. Bei zweien nicht.*

## Teil 3 — Die Reihenfolge

Wichtig, und im ersten Entwurf noch nicht so gedacht: **Erst den SSH-Zugang
einrichten und testen, dann auf privat stellen.** Nicht andersherum.

Solange das Repository öffentlich ist, funktioniert HTTPS weiter als Rückfall.
Man kann also den ganzen neuen Weg in Ruhe aufbauen und beweisen, dass er trägt,
ohne dass irgendetwas kaputt ist. Erst wenn der SSH-Abruf nachweislich läuft,
wird der Schalter umgelegt — und in dem Moment ändert sich für die NAS gar
nichts mehr.

Wer zuerst umstellt, steht mit einem toten Deploy da und muss unter Druck
debuggen.

| Schritt | Wo | Was |
|---|---|---|
| 1 | NAS, Aufgabenplaner | **Skript A** — Schlüsselpaar erzeugen, `~/.ssh/config` ergänzen |
| 2 | GitHub | Öffentlichen Schlüssel als **Deploy-Key** hinterlegen (nur lesen) |
| 3 | NAS, Aufgabenplaner | **Skript B** — SSH testen, Remote auf SSH umstellen, Abruf beweisen |
| 4 | GitHub | Repository **auf privat** stellen |
| 5 | NAS | Das **bestehende Update-Skript** einmal von Hand starten — Beweis, dass der Deploy nach der Umstellung noch läuft |

## Teil 4 — Skript A (NAS): Schlüssel erzeugen

Aufgabenplaner → **Erstellen → Geplante Aufgabe → Benutzerdefiniertes Skript**.
Benutzer: **root**. Zeitplan: **nicht wiederholen** (einmal von Hand ausführen).
Unter *Aufgabeneinstellungen* „Ausführungsdetails per E-Mail senden" anhaken —
dann kommt der öffentliche Schlüssel per Mail. Zusätzlich legt das Skript ihn in
File Station ab.

```sh
#!/bin/sh
set -e
export HOME=/root

KEY=/root/.ssh/adlerplan
OUT=/volume1/docker/adlerplan-deploykey.pub

mkdir -p /root/.ssh
chmod 700 /root/.ssh

# 1. Schluesselpaar, nur falls noch keins da ist (Skript ist wiederholbar)
if [ ! -f "$KEY" ]; then
    ssh-keygen -t ed25519 -N "" -C "adlerplan-nas-deploy" -f "$KEY"
fi
chmod 600 "$KEY"

# 2. Host-Alias eintragen, idempotent
touch /root/.ssh/config
chmod 600 /root/.ssh/config
if ! grep -q "^Host github-adlerplan$" /root/.ssh/config; then
    cat >> /root/.ssh/config <<'EOF'

Host github-adlerplan
    HostName github.com
    User git
    IdentityFile /root/.ssh/adlerplan
    IdentitiesOnly yes
EOF
fi

# 3. github.com in known_hosts, sonst haengt der Abruf an der Rueckfrage
touch /root/.ssh/known_hosts
chmod 600 /root/.ssh/known_hosts
if ! grep -q "^github.com " /root/.ssh/known_hosts; then
    ssh-keyscan -t ed25519 github.com >> /root/.ssh/known_hosts 2>/dev/null
fi

echo "=== Fingerabdruck des GitHub-Hostkeys (bitte vergleichen) ==="
ssh-keygen -lf /root/.ssh/known_hosts | grep github.com || true

# 4. Oeffentlichen Schluessel zum Abholen ablegen
cp "$KEY.pub" "$OUT"
chmod 644 "$OUT"

echo
echo "=== Oeffentlicher Schluessel (liegt auch unter $OUT) ==="
cat "$KEY.pub"
echo
echo "=== Inhalt von /root/.ssh/config ==="
cat /root/.ssh/config
```

**Nach dem Lauf zwei Dinge prüfen:**

1. Den ausgegebenen Fingerabdruck des GitHub-Hostkeys gegen die von GitHub
   veröffentlichte Liste halten (GitHub Docs → *GitHub's SSH key fingerprints*).
   Stimmt er nicht überein, hier abbrechen und nachsehen, was da antwortet.
2. In der ausgegebenen `/root/.ssh/config` nachsehen, ob beim **bestehenden**
   `Host github-adlernest` ebenfalls `IdentitiesOnly yes` steht. Fehlt das, bietet
   SSH beide Schlüssel an und GitHub ordnet unter Umständen dem falschen
   Repository zu — dann die Zeile dort von Hand ergänzen (Text-Editor in DSM oder
   ein Einzeiler-Skript). Der neue Eintrag hat sie schon.

Den öffentlichen Schlüssel holt man aus der Mail oder über File Station unter
`docker/adlerplan-deploykey.pub`. Er ist nicht geheim — das ist der öffentliche
Teil. Die Datei kann danach gelöscht werden, muss aber nicht.

## Teil 5 — GitHub: Deploy-Key hinterlegen

1. `https://github.com/burgjona/unterrichtsplaner` öffnen
2. **Settings** (Reiter oben rechts im Repository, nicht das Konto-Settings)
3. Linke Spalte: **Deploy keys**
4. **Add deploy key**
5. *Title:* `Synology NAS – adlerplan`
6. *Key:* den kompletten Inhalt von `adlerplan-deploykey.pub` einfügen —
   eine Zeile, beginnt mit `ssh-ed25519 `
7. **„Allow write access" NICHT anhaken.** Die NAS zieht nur, sie schreibt nie.
8. **Add key**

## Teil 6 — Skript B (NAS): Remote umstellen

Zweite Aufgabe im Aufgabenplaner, wieder als **root**, wieder einmalig.
Läuft, solange das Repository noch öffentlich ist — der Rückfall auf HTTPS ist
also noch da, falls etwas klemmt.

```sh
#!/bin/sh
set -e
export HOME=/root
REPO=/volume1/docker/adlerplan
SSHURL="git@github-adlerplan:burgjona/unterrichtsplaner.git"

cd "$REPO"

# safe.directory: der Ordner gehoert nicht root, git laeuft aber als root.
# Steht laut DEPLOY.md schon im Update-Skript — hier idempotent abgesichert.
if ! git config --global --get-all safe.directory 2>/dev/null | grep -qx "$REPO"; then
    git config --global --add safe.directory "$REPO"
    echo "safe.directory ergaenzt."
else
    echo "safe.directory war schon gesetzt."
fi

echo
echo "=== SSH-Authentifizierung testen ==="
# Erwartete Antwort:
#   Hi burgjona/unterrichtsplaner! You've successfully authenticated,
#   but GitHub does not provide shell access.
# Exit-Code 1 ist dabei normal.
ssh -T git@github-adlerplan 2>&1 || true

echo
echo "=== Remote vorher ==="
git remote -v

git remote set-url origin "$SSHURL"

echo
echo "=== Remote nachher ==="
git remote -v

echo
echo "=== Testabruf ueber SSH ==="
git fetch origin
git status -sb
echo
echo "FERTIG. Wenn oben 'Hi burgjona/unterrichtsplaner!' stand und der Abruf"
echo "ohne Fehler durchlief, kann das Repository auf privat gestellt werden."
```

**Erst weitermachen, wenn in der Ausgabe steht:**
`Hi burgjona/unterrichtsplaner! You've successfully authenticated`
und der `git fetch` fehlerfrei durchlief.

Steht dort stattdessen `Hi burgjona/Adlernest!`, greift der falsche Schlüssel —
dann fehlt `IdentitiesOnly yes` beim Adlernest-Eintrag (siehe Teil 4, Punkt 2).

*Rückfall, solange das Repository noch öffentlich ist:*
`git remote set-url origin https://github.com/burgjona/unterrichtsplaner.git`

## Teil 7 — GitHub: auf privat stellen

Vorher kurz unter **Insights → Forks** nachsehen, ob jemand geforkt hat. Bei
einem Wechsel von öffentlich auf privat trennt GitHub bestehende Forks ab; sie
verschwinden nicht von selbst. Erwartung hier: keine.

1. `https://github.com/burgjona/unterrichtsplaner` → **Settings**
2. Ganz nach unten scrollen bis **Danger Zone**
3. **Change repository visibility** → **Change visibility**
4. **Make private** auswählen
5. Die Warnhinweise durchlesen und bestätigen (Stars und Watcher gehen verloren —
   hier ohne Bedeutung)
6. Zur Bestätigung `burgjona/unterrichtsplaner` eintippen
7. **I understand, change repository visibility**

Nicht betroffen, weil nicht vorhanden: GitHub Actions (keine Workflows im
Repository), GitHub Pages, Lizenzdatei.

## Teil 8 — Nachweis, dass der Deploy noch läuft

Zum Schluss das **bestehende** Update-Skript im Aufgabenplaner einmal von Hand
starten (das mit `git pull` und `docker compose build`, siehe `DEPLOY.md`).

Es braucht **keine** Änderung: Es setzt bereits `export HOME=/root` — und genau
das ist der Grund, warum `/root/.ssh/config` und damit der Host-Alias gefunden
werden. Ohne diese Zeile liefe der Pull ins Leere, weil der Aufgabenplaner ohne
gesetztes `HOME` startet. Auch `git config --global --add safe.directory` steht
schon drin.

Läuft es durch, ist die Umstellung abgeschlossen und für die NAS unsichtbar
geworden.

## Checkliste

- [ ] `lp_os_musik_2019.pdf` im Arbeitsverzeichnis aufräumen (Teil 1, Punkt 3)
- [ ] Skript A auf der NAS laufen lassen, Hostkey-Fingerabdruck vergleichen
- [ ] `IdentitiesOnly yes` beim Adlernest-Eintrag prüfen
- [ ] Deploy-Key auf GitHub hinterlegen, **ohne** Schreibrechte
- [ ] Skript B laufen lassen, auf `Hi burgjona/unterrichtsplaner!` warten
- [ ] Forks prüfen, Repository auf privat stellen
- [ ] Bestehendes Update-Skript einmal von Hand starten
