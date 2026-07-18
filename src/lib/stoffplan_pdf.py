"""U19: Stoffverteilungsplan als PDF-Tabelle (reportlab).

Rendert einen gespeicherten Stoffplan (Plan-Kopf + Blöcke) als Tabelle mit den
Spalten LB-Code | Thema | UStd | Zeitraum (von–bis) | Bemerkung/Konflikt. Die
Font-Registrierung wird aus ``asuv_export`` übernommen, damit ä/ö/ü/ß korrekt
gerendert werden (Arial/Liberation mit Helvetica-Fallback).
"""
from io import BytesIO

from .asuv_export import _register_fonts


def _zeitraum(start, end) -> str:
    if start and end:
        return f"{start} – {end}"
    if start:
        return f"ab {start}"
    if end:
        return f"bis {end}"
    return "—"


def build_stoffplan_pdf(plan, blocks, class_name: str, school_year_label: str) -> bytes:
    """plan: sqlite3.Row/dict (title, status); blocks: Iterable von Row/dict.

    Liefert die PDF-Datei als bytes.
    """
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

    body_font, bold_font = _register_fonts()
    title_st = ParagraphStyle("sp_title", fontName=bold_font, fontSize=16, leading=20)
    meta_st = ParagraphStyle("sp_meta", fontName=body_font, fontSize=10, leading=14)
    head_st = ParagraphStyle("sp_head", fontName=bold_font, fontSize=9, leading=11,
                             textColor=(0.1, 0.1, 0.1), alignment=TA_LEFT)
    cell_st = ParagraphStyle("sp_cell", fontName=body_font, fontSize=9, leading=11, alignment=TA_LEFT)

    def esc(t):
        return (str(t) if t is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def p(text, style):
        return Paragraph(esc(text) or "&nbsp;", style)

    def to_dict(row):
        return row if isinstance(row, dict) else dict(row)

    plan = to_dict(plan)
    title = plan.get("title") or "Stoffverteilungsplan"
    status = plan.get("status") or "entwurf"

    story = [
        p("Stoffverteilungsplan", title_st),
        Spacer(1, 4),
        p(f"{esc(title)}", meta_st),
        p(f"Klasse: {esc(class_name)}   ·   Schuljahr: {esc(school_year_label)}   ·   Status: {esc(status)}", meta_st),
        Spacer(1, 12),
    ]

    header = [p(h, head_st) for h in ("LB-Code", "Thema", "UStd", "Zeitraum", "Bemerkung / Konflikt")]
    data = [header]
    for b in blocks:
        b = to_dict(b)
        data.append([
            p(b.get("lb_code"), cell_st),
            p(b.get("title"), cell_st),
            p("" if b.get("ustd") is None else b.get("ustd"), cell_st),
            p(_zeitraum(b.get("start_date"), b.get("end_date")), cell_st),
            p(b.get("conflict_note"), cell_st),
        ])
    if len(data) == 1:
        data.append([p("Keine Blöcke erfasst.", cell_st), "", "", "", ""])

    table = Table(data, colWidths=[2.2 * cm, 5.6 * cm, 1.3 * cm, 3.4 * cm, 4.5 * cm], repeatRows=1)
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
