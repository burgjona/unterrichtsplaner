"""Textformatierung (fett/kursiv/unterstrichen/Farbe) fuer Tafelbild-Notiz und Heftereintrag.

Zwei Ebenen: der Sanitizer selbst (src/lib/richtext.py) und der Weg durch die API — dort
muss die *_html-Spalte die Quelle der Wahrheit sein und der Klartext daneben abgeleitet,
damit Volltextsuche und Offline-Clients nichts von der Formatierung mitbekommen.
"""
import sqlite3

from src.lib.richtext import html_to_text, normalize_rich, sanitize_html


# ---------- Sanitizer ----------

def test_sanitize_keeps_the_four_formats():
    src = '<b>fett</b> <i>kursiv</i> <u>unterstrichen</u> <span class="rt-rot">rot</span>'
    assert sanitize_html(src) == src


def test_sanitize_keeps_umlauts_and_escapes_text():
    # Umlaute bleiben Umlaute (Projektkonvention), aber < & im Text werden maskiert.
    assert sanitize_html("<b>Grüße & Söhne</b>") == "<b>Grüße &amp; Söhne</b>"
    assert "<script" not in sanitize_html("a < b und 5 > 3")


def test_sanitize_drops_scripts_with_their_content():
    out = sanitize_html('Text<script>alert("x")</script>Ende')
    assert out == "TextEnde"


def test_sanitize_drops_event_handlers_and_unknown_tags_but_keeps_text():
    out = sanitize_html('<div onclick="böse()">Hallo <marquee>Welt</marquee></div>')
    assert "onclick" not in out and "marquee" not in out
    assert "Hallo" in out and "Welt" in out


def test_sanitize_drops_images_and_links():
    out = sanitize_html('<img src=x onerror=alert(1)><a href="javascript:alert(1)">klick</a>')
    assert "img" not in out and "href" not in out and "javascript" not in out
    assert "klick" in out


def test_sanitize_allows_only_palette_classes():
    assert sanitize_html('<span class="rt-gruen">gut</span>') == '<span class="rt-gruen">gut</span>'
    # Fremde Klasse -> das span faellt weg, der Text bleibt.
    assert sanitize_html('<span class="eigene-klasse">x</span>') == "x"
    # Inline-Styles gibt es hier gar nicht: kein CSS aus der Eingabe, egal was drinsteht.
    assert sanitize_html('<span style="color:#c0392b">x</span>') == "x"
    assert sanitize_html('<span style="position:fixed;background:url(javascript:1)">x</span>') == "x"
    # Neben der Palettenklasse mitgeschickte Klassen fallen weg.
    assert sanitize_html('<span class="rt-blau fremde">x</span>') == '<span class="rt-blau">x</span>'


def test_sanitize_drops_styles_even_on_allowed_tags():
    """Auch an b/i/u gibt es kein style-Attribut — es gibt hier ueberhaupt kein CSS aus der
    Eingabe. Der Editor verlagert eine Farbe deshalb in ein eigenes span nach innen
    (stylesToClasses in web/richtext.js); dieses Verschachteln muss durchkommen."""
    assert sanitize_html('<b style="color:#7e22ce">x</b>') == "<b>x</b>"
    assert sanitize_html('<b><span class="rt-violett">x</span></b>') == \
        '<b><span class="rt-violett">x</span></b>'
    assert sanitize_html('<span class="rt-gruen"><b>x</b></span>') == \
        '<span class="rt-gruen"><b>x</b></span>'


def test_sanitize_balances_broken_markup():
    assert sanitize_html("<b>offen") == "<b>offen</b>"
    assert sanitize_html("fertig</b></i>") == "fertig"
    out = sanitize_html("<b>a<i>b</b>c</i>")
    assert out.count("<b>") == out.count("</b>") and out.count("<i>") == out.count("</i>")


# ---------- Klartext-Ableitung ----------

def test_html_to_text_keeps_linebreaks_and_drops_tags():
    assert html_to_text("<div>Zeile 1</div><div>Zeile 2</div>") == "Zeile 1\nZeile 2"
    assert html_to_text("<b>Merksatz:</b><br>Ballade") == "Merksatz:\nBallade"
    assert html_to_text("<b>Grüße &amp; Söhne</b>") == "Grüße & Söhne"


def test_normalize_rich_treats_formatting_without_text_as_empty():
    # Sonst haette die Stunde einen Heftereintrag, der nichts sagt, und der Dashboard-Zaehler
    # "Heftereinträge offen" wuerde luegen.
    assert normalize_rich("<b><br></b>") == (None, None)
    assert normalize_rich("   ") == (None, None)
    assert normalize_rich(None) == (None, None)


# ---------- Weg durch die API ----------

def _mk_lesson(client, **extra):
    body = {"title": "Balladen", "subject": "Deutsch", "grade": 8}
    body.update(extra)
    r = client.post("/api/lessons", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_lesson_create_derives_plain_text_from_html(client, auth):
    l = _mk_lesson(client,
                   hefteintragHtml='<b>Merkmale</b> der <span class="rt-rot">Ballade</span>',
                   tafelbildNotizHtml="<u>Foto</u> hängt im Ordner")
    assert l["hefteintragHtml"] == '<b>Merkmale</b> der <span class="rt-rot">Ballade</span>'
    assert l["hefteintrag"] == "Merkmale der Ballade"
    assert l["tafelbildNotizHtml"] == "<u>Foto</u> hängt im Ordner"
    assert l["tafelbildNotiz"] == "Foto hängt im Ordner"


def test_lesson_update_html_overwrites_derived_plain_text(client, auth):
    l = _mk_lesson(client, hefteintragHtml="<b>alt</b>")
    r = client.put(f"/api/lessons/{l['id']}", json={"hefteintragHtml": "<i>neu und länger</i>"}).json()
    assert r["hefteintragHtml"] == "<i>neu und länger</i>"
    assert r["hefteintrag"] == "neu und länger"


def test_lesson_update_plain_only_clears_formatting(client, auth):
    """Nur Klartext geschickt = Formatierung bewusst weg (sonst laufen die Spalten auseinander)."""
    l = _mk_lesson(client, hefteintragHtml="<b>formatiert</b>")
    r = client.put(f"/api/lessons/{l['id']}", json={"hefteintrag": "schlicht"}).json()
    assert r["hefteintrag"] == "schlicht"
    assert r["hefteintragHtml"] is None


def test_lesson_rejects_script_through_the_api(client, auth):
    l = _mk_lesson(client, hefteintragHtml='<b>ok</b><script>alert(1)</script><img src=x onerror=y>')
    assert l["hefteintragHtml"] == "<b>ok</b>"
    assert "script" not in (l["hefteintragHtml"] or "")


def test_formatted_hefteintrag_stays_searchable_without_tags(client, auth, app):
    """Der Volltextindex haengt am Klartext — im Index darf kein Markup landen."""
    _mk_lesson(client, title="Stunde ohne Suchwort",
               hefteintragHtml='<b>Zauberformel</b> im <span class="rt-gruen">Hefter</span>')
    r = client.get("/api/search?q=zauberformel").json()
    assert r["total"] == 1 and r["results"][0]["type"] == "lesson"

    conn = sqlite3.connect(app.state.db_path)
    body = conn.execute("SELECT body FROM search_docs WHERE entity_type='lesson'").fetchone()[0]
    conn.close()
    assert "Zauberformel" in body
    assert "<" not in body and "span" not in body


def test_empty_html_leaves_both_columns_empty(client, auth):
    l = _mk_lesson(client, hefteintragHtml="<br>")
    assert l["hefteintragHtml"] is None and l["hefteintrag"] is None
