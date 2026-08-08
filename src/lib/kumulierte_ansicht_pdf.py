"""Kumulierte Ansicht: Stoffverteilungsplan + Sequenzplanung als ein PDF.

Je Block ein Abschnitt mit Kopfzeile (LB-Code, Thema, UStd, Zeitraum) und darunter
eine Tabelle seiner Sequenzstunden (Nr | Titel | Grobziel | Datum | Notenart). Nutzt
dieselbe Font-Registrierung wie stoffplan_pdf.py für ä/ö/ü/ß.
"""
from io import BytesIO

from .asuv_export import _register_fonts
from .stoffplan_pdf import _de_date, _zeitraum

_NOTENART_LABELS = (
    ("is_lk", "LK"), ("is_referat", "Referat"),
    ("is_komplexe_arbeit", "Komplexe Arbeit"), ("is_klassenarbeit", "Klassenarbeit"),
)


def _notenart_text(stunde: dict) -> str:
    parts = [label for key, label in _NOTENART_LABELS if stunde.get(key)]
    if stunde.get("weitere_notenart"):
        parts.append(stunde["weitere_notenart"])
    return ", ".join(parts) if parts else "—"


def build_kumulierte_ansicht_pdf(plan, blocks, class_name: str, school_year_label: str) -> bytes:
    """plan: dict (title, status); blocks: Liste von dicts mit Block-Feldern + 'stunden'
    (Liste von Sequenzstunden-dicts). Liefert die PDF-Datei als bytes."""
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

    body_font, bold_font = _register_fonts()
    title_st = ParagraphStyle("ka_title", fontName=bold_font, fontSize=16, leading=20)
    meta_st = ParagraphStyle("ka_meta", fontName=body_font, fontSize=10, leading=14)
    block_st = ParagraphStyle("ka_block", fontName=bold_font, fontSize=12, leading=15,
                              spaceBefore=10, spaceAfter=4)
    block_meta_st = ParagraphStyle("ka_block_meta", fontName=body_font, fontSize=9, leading=12,
                                   spaceAfter=6)
    head_st = ParagraphStyle("ka_head", fontName=bold_font, fontSize=9, leading=11,
                             textColor=(0.1, 0.1, 0.1), alignment=TA_LEFT)
    cell_st = ParagraphStyle("ka_cell", fontName=body_font, fontSize=9, leading=11, alignment=TA_LEFT)

    def esc(t):
        return (str(t) if t is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def p(text, style):
        return Paragraph(esc(text) or "&nbsp;", style)

    title = plan.get("title") or "Stoffverteilungsplan"
    status = plan.get("status") or "entwurf"

    story = [
        p("Kumulierte Ansicht: Stoffverteilungsplan + Sequenzplanung", title_st),
        Spacer(1, 4),
        p(f"{esc(title)}", meta_st),
        p(f"Klasse: {esc(class_name)}   ·   Schuljahr: {esc(school_year_label)}   ·   Status: {esc(status)}", meta_st),
        Spacer(1, 10),
    ]

    if not blocks:
        story.append(p("Keine Blöcke erfasst.", meta_st))

    for b in blocks:
        head = f"{b.get('lb_code') or ''} {b.get('title') or ''}".strip() or "Block"
        story.append(p(head, block_st))
        story.append(p(
            f"UStd: {b.get('ustd') if b.get('ustd') is not None else '—'}   ·   "
            f"Zeitraum: {_zeitraum(b.get('start_date'), b.get('end_date'))}",
            block_meta_st,
        ))
        stunden = b.get("stunden") or []
        header_row = [p(h, head_st) for h in ("Nr.", "Titel", "Grobziel", "Datum", "Notenart")]
        data = [header_row]
        for i, s in enumerate(stunden, start=1):
            data.append([
                p(i, cell_st),
                p(s.get("title"), cell_st),
                p(s.get("grobziel"), cell_st),
                p(_de_date(s.get("date")) if s.get("date") else "—", cell_st),
                p(_notenart_text(s), cell_st),
            ])
        if not stunden:
            data.append([p("Keine Sequenzstunden erfasst.", cell_st), "", "", "", ""])
        table = Table(data, colWidths=[1.0 * cm, 4.0 * cm, 5.3 * cm, 2.4 * cm, 3.3 * cm], repeatRows=1)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, (0.6, 0.6, 0.6)),
            ("BACKGROUND", (0, 0), (-1, 0), (0.9, 0.95, 0.9)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(table)

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm,
                            leftMargin=1.8 * cm, rightMargin=1.8 * cm)
    doc.build(story)
    return buf.getvalue()
