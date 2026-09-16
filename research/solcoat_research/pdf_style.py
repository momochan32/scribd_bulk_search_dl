"""Gaya PDF Solcoat — disalin dari solcoat_pltu_report.py (§Identitas Visual Dokumen, Project Instructions v2.6).

Palet, kop band, dan tata letak JANGAN diubah di sini; ubah di sumbernya lalu salin ulang.
Satu-satunya tambahan: teks kaki halaman menjadi parameter (dokumen riset internal ≠ penawaran).
"""

from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

GREEN = colors.HexColor("#338B34")
GREEN_DK = colors.HexColor("#1F5A20")
GREEN_LT = colors.HexColor("#EAF4EA")
GREY = colors.HexColor("#5B6560")
LINE = colors.HexColor("#C9D6CA")
ROW_ALT = colors.HexColor("#F6F9F6")
AMBER = colors.HexColor("#B26A00")
AMBER_LT = colors.HexColor("#FDF3E3")
M = 14 * mm
CW = A4[0] - 2 * M

st_title = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=15.5, leading=18.5, textColor=GREEN_DK)
st_sub = ParagraphStyle("s", fontName="Helvetica", fontSize=9.2, leading=12.4, textColor=GREY)
st_h = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=10.4, leading=13, textColor=colors.white)
st_body = ParagraphStyle("b", fontName="Helvetica", fontSize=8.5, leading=11.4, textColor=colors.HexColor("#22282A"))
st_small = ParagraphStyle("sm", fontName="Helvetica", fontSize=7.2, leading=9.4, textColor=GREY)
st_mono = ParagraphStyle("mo", fontName="Courier", fontSize=7.4, leading=10, textColor=colors.HexColor("#22282A"))
st_cw = ParagraphStyle("cw", fontName="Helvetica-Bold", fontSize=7.6, leading=9.4, textColor=colors.white)
st_c = ParagraphStyle("c", fontName="Helvetica", fontSize=7.7, leading=9.8, textColor=colors.HexColor("#22282A"))
st_cb = ParagraphStyle("cb", fontName="Helvetica-Bold", fontSize=7.7, leading=9.8, textColor=colors.HexColor("#22282A"))
st_cr = ParagraphStyle("cr", parent=st_c, alignment=2)
st_kpi = ParagraphStyle("k", fontName="Helvetica-Bold", fontSize=13.5, leading=15.5, alignment=1)
st_kpil = ParagraphStyle("kl", fontName="Helvetica", fontSize=6.9, leading=8.6, alignment=1, textColor=GREY)
st_sub_h = ParagraphStyle("sh", fontName="Helvetica-Bold", fontSize=8.8, leading=11.5, textColor=GREEN_DK,
                          spaceBefore=5, spaceAfter=2)


def safe(text) -> str:
    """Escape XML + ganti karakter di luar WinAnsi agar font standar tidak mencetak kotak hitam."""
    raw = "" if text is None else str(text)
    return escape(raw.encode("cp1252", "replace").decode("cp1252"))


def P(t, s=st_c):
    return Paragraph(t, s)


def num(v, d=0):
    return f"{v:,.{d}f}".replace(",", "@").replace(".", ",").replace("@", ".")


def H(txt):
    t = Table([[P(txt, st_h)]], colWidths=[CW], rowHeights=[14.5])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), GREEN), ("LEFTPADDING", (0, 0), (-1, -1), 6),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    return KeepTogether([Spacer(1, 6), t, Spacer(1, 3)])


def grid(rows, widths):
    t = Table(rows, colWidths=widths, repeatRows=1)
    cmds = [("GRID", (0, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3.5), ("RIGHTPADDING", (0, 0), (-1, -1), 3.5),
            ("TOPPADDING", (0, 0), (-1, -1), 2.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6),
            ("BACKGROUND", (0, 0), (-1, 0), GREEN_DK)]
    for i in range(1, len(rows)):
        if i % 2 == 0:
            cmds.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    t.setStyle(TableStyle(cmds))
    return t


def kpirow(items):
    cells, w = [], CW / len(items)
    for val, lab in items:
        inner = Table([[Paragraph(val, ParagraphStyle("kv", parent=st_kpi, textColor=GREEN_DK))],
                       [Paragraph(lab, st_kpil)]], colWidths=[w - 6])
        inner.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
        cells.append(inner)
    t = Table([cells], colWidths=[w] * len(items))
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), GREEN_LT), ("GRID", (0, 0), (-1, -1), 0.4, colors.white),
                           ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    return t


def callout(text):
    """Callout amber — hanya untuk dokumen internal (aturan palet Solcoat)."""
    t = Table([[P(text, st_body)]], colWidths=[CW])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), AMBER_LT), ("LINEBEFORE", (0, 0), (0, -1), 2.2, AMBER),
                           ("LEFTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return t


def render(path, hdr_r, band, title, subtitle, flow, footer):
    def deco(cv, doc):
        cv.saveState()
        y = A4[1] - 9 * mm
        cv.setFont("Helvetica-Bold", 7.4); cv.setFillColor(GREEN_DK)
        cv.drawString(M, y, "SOLCOAT HIGH EMISSIVITY COATING")
        cv.setFont("Helvetica", 7.4); cv.setFillColor(GREY)
        cv.drawRightString(A4[0] - M, y, hdr_r)
        cv.setStrokeColor(GREEN); cv.setLineWidth(1.1)
        cv.line(M, y - 2.6 * mm, A4[0] - M, y - 2.6 * mm)
        cv.setFont("Helvetica", 6.6)
        cv.drawString(M, y - 5.4 * mm, band)
        cv.drawRightString(A4[0] - M, y - 5.4 * mm, "Halaman %d" % doc.page)
        cv.setStrokeColor(LINE); cv.setLineWidth(0.5)
        cv.line(M, 11 * mm, A4[0] - M, 11 * mm)
        cv.setFont("Helvetica", 6.4)
        cv.drawString(M, 7.6 * mm, footer)
        cv.restoreState()
    doc = BaseDocTemplate(str(path), pagesize=A4, leftMargin=M, rightMargin=M,
                          topMargin=M + 9 * mm, bottomMargin=14 * mm, title=title)
    doc.addPageTemplates([PageTemplate(id="n", frames=[
        Frame(M, 14 * mm, CW, A4[1] - M - 9 * mm - 14 * mm, leftPadding=0, rightPadding=0,
              topPadding=0, bottomPadding=0)], onPage=deco)])
    doc.build([Paragraph(title, st_title), Spacer(1, 2.5), Paragraph(subtitle, st_sub), Spacer(1, 7)] + flow)
