"""Rich-Text fuer die Freitextfelder "Notiz zum Tafelbild" und "Heftereintrag der SuS".

Erlaubt ist genau, was die Toolbar im Frontend erzeugen kann: fett, kursiv, unterstrichen
und Schriftfarbe aus einer festen Palette. Alles andere wird entfernt — der Server ist die
letzte Instanz, nicht das Frontend: was hier durchkommt, wird spaeter per innerHTML
gerendert, und die Projektkonvention (esc() fuer alles Dynamische) macht genau an dieser
Stelle eine bewusste Ausnahme.

Zu jedem HTML gehoert ein abgeleiteter Klartext (siehe 065_richtext.sql): er landet in der
alten Spalte, haelt den Volltextindex frei von Tags und bleibt fuer alles lesbar, was mit
Formatierung nichts anfangen kann.
"""
import re
from html import escape
from html.parser import HTMLParser

# Nur Formatierung, keine Struktur, keine Links, keine Bilder. div/p/br entstehen beim
# Tippen in contenteditable von selbst (Zeilenumbrueche) und muessen deshalb mit durch.
ALLOWED_TAGS = frozenset({"b", "strong", "i", "em", "u", "span", "br", "div", "p"})
_VOID_TAGS = frozenset({"br"})
# Tags, deren Ende im Klartext einen Zeilenumbruch bedeutet.
_BREAK_TAGS = frozenset({"br", "div", "p"})
# Inhalt dieser Tags faellt komplett weg (nicht nur das Tag selbst).
_DROP_CONTENT_TAGS = frozenset({"script", "style", "template"})

# Farbe kommt als Klasse aus einer festen Palette, NICHT als Inline-Style. Zwei Gruende:
# die Klassen sind in styles.css je Theme definiert (fester Hex-Wert waere in den vier
# dunklen Themes unlesbar — auf Weiss UND auf dunklem Grund erreicht keine einzelne Farbe
# WCAG AA), und ein style-Attribut gaebe es hier gar nicht erst, das man pruefen muesste.
COLOR_CLASSES = frozenset({"rt-rot", "rt-orange", "rt-gruen", "rt-blau", "rt-violett"})


def _safe_class(value: str) -> str:
    """Gibt die Palettenklasse zurueck, wenn class genau eine davon nennt, sonst ''."""
    for token in (value or "").split():
        if token in COLOR_CLASSES:
            return token
    return ""


class _Sanitizer(HTMLParser):
    """Baut das HTML neu auf, statt Verbotenes herauszuschneiden.

    Nur was hier aktiv geschrieben wird, kommt im Ergebnis vor — ein unbekanntes Tag
    verliert sein Markup, sein Text bleibt. Ein Stack merkt sich, welche oeffnenden Tags
    tatsaechlich ausgegeben wurden, damit die Ausgabe auch bei kaputter Eingabe
    (fehlende oder ueberzaehlige schliessende Tags) ausgeglichen bleibt.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list = []
        self._stack: list = []      # [(tag, emitted)]
        self._skip_depth = 0        # > 0: wir stecken in script/style/template

    def handle_starttag(self, tag, attrs):
        if self._skip_depth:
            if tag in _DROP_CONTENT_TAGS:
                self._skip_depth += 1
            return
        if tag in _DROP_CONTENT_TAGS:
            self._skip_depth = 1
            return
        if tag in _VOID_TAGS:
            if tag in ALLOWED_TAGS:
                self.out.append(f"<{tag}>")
            return
        if tag not in ALLOWED_TAGS:
            self._stack.append((tag, False))
            return
        if tag == "span":
            # Ein span ohne Palettenklasse traegt nichts bei und faellt weg (Text bleibt).
            cls = _safe_class(dict(attrs).get("class") or "")
            if not cls:
                self._stack.append((tag, False))
                return
            self.out.append(f'<span class="{cls}">')
        else:
            self.out.append(f"<{tag}>")
        self._stack.append((tag, True))

    def handle_startendtag(self, tag, attrs):
        if not self._skip_depth and tag in _VOID_TAGS and tag in ALLOWED_TAGS:
            self.out.append(f"<{tag}>")

    def handle_endtag(self, tag):
        if self._skip_depth:
            if tag in _DROP_CONTENT_TAGS:
                self._skip_depth -= 1
            return
        if tag in _VOID_TAGS:
            return
        # Zum passenden oeffnenden Tag zurueckspulen; alles darueber war ohnehin unbalanciert.
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                for open_tag, emitted in reversed(self._stack[i:]):
                    if emitted:
                        self.out.append(f"</{open_tag}>")
                del self._stack[i:]
                return
        # Schliessendes Tag ohne oeffnendes: ignorieren.

    def handle_data(self, data):
        if not self._skip_depth:
            self.out.append(escape(data, quote=False))

    def result(self) -> str:
        for tag, emitted in reversed(self._stack):
            if emitted:
                self.out.append(f"</{tag}>")
        self._stack.clear()
        return "".join(self.out)


class _TextExtractor(HTMLParser):
    """Klartext aus (bereits bereinigtem) HTML — fuer Volltextsuche und alte Clients."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list = []

    # Umbruch nur am ANFANG eines Blocks: contenteditable schreibt jede Zeile als eigenes
    # <div>, und ein Umbruch an beiden Enden machte aus jeder Zeile einen Absatz mit Leerzeile.
    # Eine wirklich leere Zeile ist "<div><br></div>" und ergibt so weiterhin zwei Umbrueche.
    def handle_starttag(self, tag, attrs):
        if tag in _BREAK_TAGS:
            self.parts.append("\n")

    handle_startendtag = handle_starttag

    def handle_data(self, data):
        self.parts.append(data)


def sanitize_html(value) -> str:
    """Reduziert value auf die erlaubte Formatierung. Nie None, immer wohlgeformt."""
    if not value:
        return ""
    p = _Sanitizer()
    p.feed(str(value))
    p.close()
    return p.result()


def html_to_text(value) -> str:
    """Klartext aus HTML: Tags weg, Umbrueche erhalten, keine Leerzeilenwueste."""
    if not value:
        return ""
    p = _TextExtractor()
    p.feed(str(value))
    p.close()
    text = "".join(p.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_rich(value):
    """(html, klartext) fuer die Speicherung — beide None, wenn nichts Sichtbares uebrig ist.

    Ein Feld, in dem nur noch Formatierung ohne Text steht (z. B. "<b><br></b>"), gilt als
    leer: sonst haette die Stunde einen Heftereintrag, der nichts sagt, und die Zaehler auf
    dem Dashboard ("Heftereinträge offen") wuerden luegen.
    """
    if value is None:
        return None, None
    html = sanitize_html(value)
    text = html_to_text(html)
    if not text:
        return None, None
    return html, text
