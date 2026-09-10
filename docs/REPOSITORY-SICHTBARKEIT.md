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
