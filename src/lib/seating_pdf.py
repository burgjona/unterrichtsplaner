"""Sitzplan-Export als PDF (U18). Rendert das Platz-Raster mit Schülernamen als Tabelle.

build_pdf erhält den Sitzplan-Namen, die Klassenbezeichnung, rows/cols und die Platzliste
(seats: [{row,col,name?}]) und liefert die Datei als bytes. Font-Registrierung analog
asuv_export (_register_fonts), damit Umlaute korrekt gesetzt werden. Die Tafel/Vorderseite
wird oben angedeutet, damit die Ausrichtung des Plans klar ist.
"""
from io import BytesIO
from typing import List, Optional

# Font-Registrierung aus dem ASUV-Export wiederverwenden (Arial/Helvetica-Fallback).
from .asuv_export import _register_fonts


def build_pdf(plan_name: str, class_label: str, rows: Optional[int], cols: Optional[int],
              seats: List[dict]) -> bytes:
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle)

    body_font, bold_font = _register_fonts()
    title_st = ParagraphStyle("title", fontName=bold_font, fontSize=16, leading=20,
                              alignment=TA_CENTER, spaceAfter=4)
    sub_st = ParagraphStyle("sub", fontName=body_font, fontSize=10, leading=14,
                            alignment=TA_CENTER, spaceAfter=10)
    board_st = ParagraphStyle("board", fontName=bold_font, fontSize=10, leading=14,
                              alignment=TA_CENTER)
    cell_st = ParagraphStyle("cell", fontName=body_font, fontSize=10, leading=13,
                             alignment=TA_CENTER)

    # Rasterdimension aus den Plätzen ableiten, falls rows/cols fehlen.
    max_row = max([s.get("row", 0) for s in seats], default=-1)
    max_col = max([s.get("col", 0) for s in seats], default=-1)
    n_rows = rows if rows and rows > 0 else max_row + 1
    n_cols = cols if cols and cols > 0 else max_col + 1
    n_rows = max(n_rows, 1)
    n_cols = max(n_cols, 1)

    def esc(t):
        return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Platz -> Name als Matrix füllen.
    grid = [["" for _ in range(n_cols)] for _ in range(n_rows)]
    for s in seats:
        r, c = s.get("row"), s.get("col")
        if r is None or c is None:
            continue
        if 0 <= r < n_rows and 0 <= c < n_cols:
            grid[r][c] = s.get("name") or ""

    data = [[Paragraph(esc(grid[r][c]) or "&nbsp;", cell_st) for c in range(n_cols)]
            for r in range(n_rows)]

    buf = BytesIO()
    page = landscape(A4)
    doc = BaseDocTemplate(buf, pagesize=page, topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                          leftMargin=1.5 * cm, rightMargin=1.5 * cm)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame])])

    story = [
        Paragraph("Sitzplan: " + esc(plan_name), title_st),
        Paragraph(esc(class_label), sub_st),
    ]

    # Tafel/Vorderseite andeuten (volle Breite).
    board = Table([[Paragraph("Tafel / Vorne", board_st)]], colWidths=[doc.width])
    board.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), (0.85, 0.9, 0.85)),
        ("BOX", (0, 0), (-1, -1), 0.5, (0.5, 0.5, 0.5)),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [board, Spacer(1, 0.6 * cm)]

    col_w = doc.width / n_cols
    row_h = min(2.4 * cm, (doc.height - 3 * cm) / n_rows) if n_rows else 2.4 * cm
    table = Table(data, colWidths=[col_w] * n_cols, rowHeights=[row_h] * n_rows)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.75, (0.4, 0.4, 0.4)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, -1), (0.98, 0.98, 1.0)),
    ]))
    story.append(table)

    doc.build(story)
    return buf.getvalue()
