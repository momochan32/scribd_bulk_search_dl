# -*- coding: utf-8 -*-
"""
SOLCOAT - Generator Laporan Kalkulasi PLTU
Versi format 1.0 - 4 September 2026

Cara pakai: isi satu dict UNIT (lihat contoh di bawah), lalu jalankan.
    python3 solcoat_pltu_report.py
Struktur 9 bagian dan seluruh aturannya dikunci di sini - jangan diubah per dokumen.
Spesifikasi lengkap ada di file kanon 16-format-laporan-pltu.md
"""
import math
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
                                Spacer, Table, TableStyle, KeepTogether)

# ============================== GAYA - JANGAN DIUBAH ==============================
GREEN = colors.HexColor("#338B34")
GREEN_DK = colors.HexColor("#1F5A20")
GREEN_LT = colors.HexColor("#EAF4EA")
GREY = colors.HexColor("#5B6560")
LINE = colors.HexColor("#C9D6CA")
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
st_crb = ParagraphStyle("crb", parent=st_cb, alignment=2)
st_kpi = ParagraphStyle("k", fontName="Helvetica-Bold", fontSize=13.5, leading=15.5, alignment=1)
st_kpil = ParagraphStyle("kl", fontName="Helvetica", fontSize=6.9, leading=8.6, alignment=1, textColor=GREY)


def P(t, s=st_c):
    return Paragraph(t, s)


def rp(v):
    return "Rp " + f"{round(v):,}".replace(",", ".")


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
            cmds.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F6F9F6")))
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


def render(path, hdr_r, band, title, subtitle, flow):
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
        cv.drawString(M, 7.6 * mm, "PT SOLCOAT INDO JAYA  -  Untuk diskusi teknis, bukan penawaran mengikat")
        cv.restoreState()
    doc = BaseDocTemplate(path, pagesize=A4, leftMargin=M, rightMargin=M,
                          topMargin=M + 9 * mm, bottomMargin=14 * mm, title=title)
    doc.addPageTemplates([PageTemplate(id="n", frames=[
        Frame(M, 14 * mm, CW, A4[1] - M - 9 * mm - 14 * mm, leftPadding=0, rightPadding=0,
              topPadding=0, bottomPadding=0)], onPage=deco)])
    doc.build([Paragraph(title, st_title), Spacer(1, 2.5), Paragraph(subtitle, st_sub), Spacer(1, 7)] + flow)


# ============================== KONSTANTA PLN 2025 ==============================
# Otoritas: 15-data-pln-np-2025.md - jangan diubah per dokumen
BPP_2025 = 1283.23          # Rp/kWh  [U] LT PLN NP 2025 hal. 399
FUEL_PLTU = 661.80          # Rp/kWh  [A] turunan Catatan 21 hal. 961 : produksi hal. 299
BPP_LAMA = 908.15           # Rp/kWh  [U] BPP Jawa-Bali basis 2020
FUEL_LAMA = 619.00          # Rp/kWh  [A] turunan
NILAI_BAWAH = 289_000       # Rp/MWh
NILAI_ATAS = 621_000        # Rp/MWh
SHARE_DEPOSIT = 0.025       # [U] NERC GADS 1995-2004
JAM = 8760
COV_CAST, COV_FIB = 3.50, 2.50
SKENARIO = [("Konservatif", 0.15), ("Menengah", 0.30), ("Atas", 0.50)]

ZONA_LUAR_DEFAULT = [
    ("Elemen air preheater", "100-350 C", "Di bawah suhu curing"),
    ("Economizer hopper dan casing backpass", "300-400 C", "Di bawah suhu curing"),
    ("Ducting gas buang, inlet ESP, stack liner", "130-350 C", "Di bawah suhu curing"),
    ("Bagian dalam pulverizer dan elbow coal pipe", "60-90 C", "Di bawah suhu curing"),
]


def build(u):
    cast = sum(a for _, a in u["cast"])
    fib = sum(a for _, a in u["fib"])
    gc = math.ceil(cast / COV_CAST / 10) * 10
    gf = math.ceil(fib / COV_FIB / 10) * 10
    GAL = u.get("galon_override", gc + gf)
    INV = GAL * u["harga_gal"]
    TOT = sum(s["nilai"] for s in u["streams"])
    bruto = u["mw"] * JAM
    lost = bruto * (1 - u["eaf"] / 100)
    dep = lost * SHARE_DEPOSIT
    PB, PA = dep * NILAI_BAWAH, dep * NILAI_ATAS
    pb30 = INV / (TOT * 0.30 + PB * 0.30) * 12

    F = [kpirow([(f"{cast+fib} m2", "Area berlining refraktori<br/>dalam lingkup pekerjaan"),
                 (f"{GAL} galon", "Kebutuhan material"),
                 ("Rp " + num(INV / 1e9, 2) + " M", "Nilai investasi material"),
                 (f"{pb30:.0f} bulan", "Payback pada skenario<br/>menengah 30%")]), Spacer(1, 7)]

    # 1
    F.append(H("1 - Identifikasi Unit"))
    F.append(grid([[P("Parameter", st_cw), P("Keterangan", st_cw)]] +
                  [[P(k, st_cb), P(v, st_c)] for k, v in u["ident"]], [CW * 0.24, CW * 0.76]))
    F.append(Spacer(1, 4))
    F.append(P(f"<b>Data kinerja operasi {u['up']} tahun 2025</b>", st_body))
    F.append(Spacer(1, 2))
    F.append(grid([
        [P("Indikator", st_cw), P(u["up"], st_cw), P("Armada PLTU PLN NP", st_cw)],
        [P("EAF - faktor kesiapan", st_c), P(f"<b>{u['eaf_s']}%</b>", st_crb), P("86,86%", st_cr)],
        [P("SOF - pemeliharaan terencana", st_c), P(f"<b>{u['sof']}%</b>", st_crb), P("10,90%", st_cr)],
        [P("EFOR - gangguan paksa", st_c), P(f"<b>{u['efor']}%</b>", st_crb), P("1,92%", st_cr)],
        [P("NPHR", st_c), P(f"<b>{u['nphr']} kCal/kWh</b>", st_crb), P("3.196,43 kCal/kWh", st_cr)],
        [P("Produksi tenaga listrik", st_c), P(f"<b>{u['prod_gwh']} GWh</b>", st_crb), P("36.336,07 GWh", st_cr)],
        [P("Daya terpasang", st_c), P(f"<b>{u['dtp']} MW</b>", st_crb), P("6.239,50 MW", st_cr)],
    ], [CW * 0.34, CW * 0.33, CW * 0.33]))

    # 2
    F.append(H("2 - Lingkup Pekerjaan"))
    F.append(P("Coating diaplikasikan pada permukaan refraktori dan serat keramik. Zona yang masuk lingkup "
               "adalah zona yang permukaannya refraktori atau serat keramik dan suhu kerjanya melewati 500 "
               "derajat C sehingga coating dapat mengalami curing.", st_body))
    F.append(Spacer(1, 3))
    rows = [[P("Zona hot face", st_cw), P("Luas", st_cw), P("Substrat", st_cw)]]
    for n, a in u["cast"]:
        rows.append([P(n, st_c), P(f"{a} m2", st_cr), P("Castable", st_c)])
    for n, a in u["fib"]:
        rows.append([P(n, st_c), P(f"{a} m2", st_cr), P("Ceramic fiber", st_c)])
    rows.append([P("<b>Total area dalam lingkup</b>", st_cb), P(f"<b>{cast+fib} m2</b>", st_crb),
                 P(f"<b>{cast} castable dan {fib} fiber</b>", st_cb)])
    F.append(grid(rows, [CW * 0.52, CW * 0.14, CW * 0.34]))
    F.append(Spacer(1, 4))
    F.append(P("<b>Zona di luar lingkup</b>", st_body))
    F.append(Spacer(1, 2))
    F.append(grid([[P("Zona", st_cw), P("Suhu kerja", st_cw), P("Keterangan", st_cw)]] +
                  [[P(a, st_c), P(b, st_c), P(c, st_c)] for a, b, c in u["zona_luar"]],
                  [CW * 0.34, CW * 0.16, CW * 0.50]))

    # 3
    F.append(H("3 - Nilai Investasi"))
    rows = [[P("Butir", st_cw), P("Nilai", st_cw)],
            [P("Total area dalam lingkup", st_c), P(f"{cast+fib} m2", st_cr)],
            [P("Kebutuhan material", st_c), P(f"{GAL} galon", st_cr)]]
    if u.get("tampilkan_harga_galon", True):
        rows.append([P("Harga per galon", st_c), P(rp(u["harga_gal"]), st_cr)])
    rows.append([P("<b>TOTAL INVESTASI MATERIAL</b>", st_cb), P("<b>" + rp(INV) + "</b>", st_crb)])
    F.append(grid(rows, [CW * 0.62, CW * 0.38]))
    F.append(Spacer(1, 3))
    F.append(P("Nilai di atas sudah mencakup biaya material dan biaya pengerjaan, meliputi surface preparation, "
               "aplikasi, dan supervisi. Perancah dan akses kerja disediakan oleh pemilik unit.", st_small))

    # 4
    F.append(H("4 - Empat Mekanisme yang Ditangani"))
    F.append(grid([[P("Mekanisme", st_cw), P("Yang terjadi pada permukaan", st_cw), P("Yang dapat diukur", st_cw)]] +
                  [[P(a, st_cb), P(b, st_c), P(c, st_c)] for a, b, c in u["mekanisme"]],
                  [CW * 0.20, CW * 0.44, CW * 0.36]))

    # 5
    F.append(H("5 - Biaya Perawatan yang Dihindari"))
    rows = [[P("Komponen atau pekerjaan", st_cw), P("Dasar perhitungan", st_cw), P("Nilai tahunan penuh", st_cw)]]
    for s in u["streams"]:
        rows.append([P(s["nama"], st_c), P(s["dasar"], st_c), P(rp(s["nilai"]), st_cr)])
    rows.append([P("<b>Total pada efektivitas penuh</b>", st_cb), P("", st_c), P("<b>" + rp(TOT) + "</b>", st_crb)])
    F.append(grid(rows, [CW * 0.26, CW * 0.54, CW * 0.20]))
    F.append(Spacer(1, 3))
    F.append(P(u["tidak_dihitung"], st_small))

    # 6
    F.append(H("6 - Produksi yang Tidak Jadi Hilang"))
    F.append(P("Setiap penghentian atau penurunan beban untuk merontokkan deposit berarti produksi yang hilang. "
               "Nilainya dihitung dari selisih biaya pokok penyediaan pembangkitan terhadap biaya bahan bakar, "
               "karena batu bara yang tidak jadi dibakar merupakan penghematan yang harus dikurangkan.", st_body))
    F.append(Spacer(1, 3))
    F.append(grid([
        [P("Butir", st_cw), P("Nilai", st_cw), P("Dasar", st_cw)],
        [P("Produksi bruto teoretis", st_c), P(num(bruto) + " MWh/tahun", st_cr), P(f"{u['mw']} MW x 8.760 jam", st_c)],
        [P("EAF", st_c), P(f"{u['eaf_s']}%", st_cr), P(f"Realisasi {u['up']} 2025", st_c)],
        [P("Kehilangan produksi tahunan", st_c), P(num(lost) + " MWh/tahun", st_cr),
         P(num(bruto) + f" x (1 - 0,{u['eaf_s'].replace(',', '')})", st_c)],
        [P("Porsi terkait deposisi abu", st_c), P(num(dep) + " MWh/tahun", st_cr), P("2,5% dari kehilangan produksi", st_c)],
        [P("Nilai energi pengganti - batas bawah", st_c), P("Rp 289.000/MWh", st_cr),
         P("Biaya Pokok Penyediaan Jawa-Bali Rp 908,15/kWh dikurangi biaya bahan bakar Rp 619/kWh", st_c)],
        [P("Nilai energi pengganti - batas atas", st_c), P("Rp 621.000/MWh", st_cr),
         P("Biaya Pokok Penyediaan pembangkit 2025 Rp 1.283,23/kWh dikurangi biaya bahan bakar PLTU Rp 661,80/kWh", st_c)],
        [P("<b>Nilai aliran produksi pada efektivitas penuh - batas bawah</b>", st_cb), P("<b>" + rp(PB) + "</b>", st_crb),
         P(num(dep, 2) + " MWh x Rp 289.000", st_c)],
        [P("<b>Nilai aliran produksi pada efektivitas penuh - batas atas</b>", st_cb), P("<b>" + rp(PA) + "</b>", st_crb),
         P(num(dep, 2) + " MWh x Rp 621.000", st_c)],
    ], [CW * 0.26, CW * 0.22, CW * 0.52]))
    F.append(Spacer(1, 3))
    sp = "&nbsp;" * 26
    F.append(P(
        f"Produksi bruto teoretis   = {u['mw']} MW x 8.760 jam = {num(bruto)} MWh per tahun<br/>"
        f"Kehilangan produksi       = {num(bruto)} x (1 - 0,{u['eaf_s'].replace(',', '')}) = {num(lost, 2)} MWh per tahun<br/>"
        f"Porsi terkait deposit     = {num(lost, 2)} x 2,5% = {num(dep, 2)} MWh per tahun<br/><br/>"
        "Biaya bahan bakar PLTU    = (Rp 23.469.505 juta batu bara + Rp 577.579 juta biomassa) : 36.336,07 GWh<br/>"
        f"{sp}= Rp 661,80 per kWh<br/><br/>"
        "Nilai energi batas bawah  = Rp 908,15/kWh - Rp 619,00/kWh = Rp 289,15/kWh<br/>"
        f"{sp}= Rp 289.000 per MWh, dibulatkan ke bawah<br/>"
        "Nilai energi batas atas   = Rp 1.283,23/kWh - Rp 661,80/kWh = Rp 621,43/kWh<br/>"
        f"{sp}= Rp 621.000 per MWh, dibulatkan ke bawah<br/><br/>"
        f"Aliran produksi bawah     = {num(dep, 2)} MWh x Rp 289.000 = {rp(PB)} per tahun<br/>"
        f"Aliran produksi atas      = {num(dep, 2)} MWh x Rp 621.000 = {rp(PA)} per tahun", st_mono))

    # 7
    F.append(H("7 - Payback dan ROI"))
    F.append(P("Persentase pada tabel di bawah adalah pengurangan frekuensi penggantian komponen dan pekerjaan "
               "pembersihan yang terkait deposit dan abrasi.", st_body))

    def tabel(judul, basis, kolom_split, dasar_txt):
        F.append(Spacer(1, 3))
        F.append(P(f"<b>{judul}</b>", st_body))
        F.append(Spacer(1, 2))
        if kolom_split:
            rows = [[P("Skenario", st_cw), P("Reduksi", st_cw), P("Perawatan", st_cw), P("Produksi", st_cw),
                     P("Total manfaat per tahun", st_cw), P("ROI tahun pertama", st_cw), P("Payback", st_cw)]]
            rows.append([P("<b>Basis - efektivitas penuh</b>", st_cb), P("<b>100%</b>", st_crb),
                         P("<b>" + rp(TOT) + "</b>", st_crb), P("<b>" + rp(basis - TOT) + "</b>", st_crb),
                         P("<b>" + rp(basis) + "</b>", st_crb),
                         P(num((basis - INV) / INV * 100, 1) + "%", st_cr), P(f"{INV/basis*12:.0f} bulan", st_cr)])
            for nm, r in SKENARIO:
                t = basis * r
                rows.append([P(nm, st_cb), P(f"{int(r*100)}%", st_cr), P(rp(TOT * r), st_cr),
                             P(rp((basis - TOT) * r), st_cr), P("<b>" + rp(t) + "</b>", st_crb),
                             P(num((t - INV) / INV * 100, 1) + "%", st_cr), P(f"<b>{INV/t*12:.0f} bulan</b>", st_crb)])
            F.append(grid(rows, [CW * .14, CW * .09, CW * .16, CW * .16, CW * .19, CW * .14, CW * .12]))
        else:
            rows = [[P("Skenario", st_cw), P("Reduksi", st_cw), P("Total manfaat per tahun", st_cw),
                     P("ROI tahun pertama", st_cw), P("Payback", st_cw)]]
            rows.append([P("<b>Basis - efektivitas penuh</b>", st_cb), P("<b>100%</b>", st_crb),
                         P("<b>" + rp(basis) + "</b>", st_crb),
                         P(num((basis - INV) / INV * 100, 1) + "%", st_cr), P(f"{INV/basis*12:.0f} bulan", st_cr)])
            for nm, r in SKENARIO:
                t = basis * r
                rows.append([P(nm, st_cb), P(f"{int(r*100)}%", st_cr), P(rp(t), st_cr),
                             P(num((t - INV) / INV * 100, 1) + "%", st_cr), P(f"<b>{INV/t*12:.0f} bulan</b>", st_crb)])
            F.append(grid(rows, [CW * .18, CW * .12, CW * .26, CW * .22, CW * .22]))
        F.append(Spacer(1, 2))
        F.append(P(dasar_txt + "<br/>Manfaat skenario = basis 100% x persentase reduksi", st_mono))

    tabel("Berbasis biaya perawatan yang dihindari saja", TOT, False,
          f"Basis 100% = total Bagian 5 = {rp(TOT)} per tahun")
    tabel("Berbasis biaya perawatan ditambah produksi yang tidak jadi hilang", TOT + PB, True,
          f"Basis 100% = perawatan {rp(TOT)} + produksi {rp(PB)} = {rp(TOT+PB)} per tahun")
    tabel("Pada batas atas nilai energi pengganti Rp 621.000 per MWh", TOT + PA, False,
          f"Basis 100% = perawatan {rp(TOT)} + produksi {rp(PA)} = {rp(TOT+PA)} per tahun")
    F.append(Spacer(1, 4))
    F.append(P(f"Total investasi = {GAL} galon x {rp(u['harga_gal'])} = {rp(INV)}<br/>"
               "ROI tahun pertama = (manfaat tahunan - total investasi) : total investasi<br/>"
               "Payback dalam bulan = total investasi : manfaat tahunan x 12", st_mono))

    # 8
    F.append(H("8 - Sensitivitas terhadap Riwayat Penggantian Aktual"))
    F.append(P("Interval pada Bagian 5 adalah <b>frekuensi penggantian yang berlaku saat ini di unit, sebelum "
               "dilapisi</b> - bukan interval setelah coating. Tabel di bawah menjawab satu pertanyaan: "
               "bagaimana hasil perhitungan berubah bila riwayat penggantian sebenarnya ternyata lebih jarang "
               "daripada yang kami asumsikan.", st_body))
    F.append(Spacer(1, 3))
    rows = [[P("Riwayat penggantian aktual di unit, tanpa coating", st_cw),
             P("Beban perawatan tahunan yang menjadi dasar", st_cw),
             P("Manfaat pada reduksi 30%", st_cw), P("Payback gabungan", st_cw)]]
    for lbl, f in [(u["interval_label"], 1), ("Dua kali lebih jarang<br/>" + u["interval_2x"], 2),
                   ("Empat kali lebih jarang<br/>" + u["interval_4x"], 4)]:
        base = sum(s["nilai"] / f if s.get("skala_interval", True) else s["nilai"] for s in u["streams"])
        t = base * 0.30 + PB * 0.30
        sa, sb = (st_cb, st_crb) if f == 1 else (st_c, st_cr)
        rows.append([P(lbl, sa), P(rp(base), sb), P(rp(base * 0.30), sb),
                     P(("<b>" if f == 1 else "") + f"{INV/t*12:.0f} bulan" + ("</b>" if f == 1 else ""), sb)])
    F.append(grid(rows, [CW * 0.36, CW * 0.22, CW * 0.20, CW * 0.22]))
    F.append(Spacer(1, 3))
    F.append(P("<b>Yang dimaksud interval pada tabel ini</b>", st_body))
    F.append(Spacer(1, 2))
    F.append(grid([
        [P("Interval pada tabel ini ADALAH", st_cw), P("Interval pada tabel ini BUKAN", st_cw)],
        [P("Frekuensi penggantian yang sudah berlaku di unit saat ini, sebelum permukaan dilapisi. Angka ini "
           "menggambarkan beban perawatan yang sedang berjalan dan menjadi dasar perhitungan manfaat", st_c),
         P("Frekuensi penggantian setelah permukaan dilapisi. Perpanjangan interval yang dihasilkan coating "
           "tidak berada di kolom ini, melainkan di dalam persentase reduksi pada Bagian 7", st_c)],
    ], [CW * 0.50, CW * 0.50]))
    F.append(Spacer(1, 3))
    F.append(P("Manfaat yang dapat diklaim adalah <b>selisih</b> antara beban perawatan sebelum dan sesudah "
               "dilapisi, bukan seluruh beban perawatan itu sendiri. Penghematan yang sudah dinikmati unit "
               "sebelum coating dipasang bukan hasil pekerjaan ini dan tidak dihitung. Karena itu, unit yang "
               "saat ini sering mengganti komponen memiliki nilai manfaat lebih besar, sementara unit yang "
               "sudah jarang mengganti komponen memiliki nilai manfaat lebih kecil - dengan kinerja coating "
               "yang sama persis pada keduanya.", st_small))
    F.append(Spacer(1, 2))
    F.append(P(u["ilustrasi_interval"], st_small))
    F.append(Spacer(1, 2))
    F.append(P("Perpanjangan interval akibat coating sudah terkandung di dalam persentase reduksi pada "
               "Bagian 7. Karena itu kolom riwayat pada tabel di atas dan persentase reduksi pada Bagian 7 "
               "tidak boleh dinaikkan bersamaan, karena akan menghitung manfaat yang sama dua kali.", st_small))
    F.append(Spacer(1, 2))
    F.append(P("Riwayat penggantian pada dua overhaul terakhir akan menggantikan seluruh baris ini.", st_small))

    # 9
    F.append(H("9 - Sumber Data dan Dasar Perhitungan"))
    F.append(grid([[P("Butir", st_cw), P("Nilai yang dipakai", st_cw), P("Sumber", st_cw)]] +
                  [[P(a, st_cb), P(b, st_c), P(c, st_c)] for a, b, c in u["sumber"]],
                  [CW * 0.20, CW * 0.30, CW * 0.50]))
    F.append(Spacer(1, 5))
    F.append(P("Perhitungan ini disusun untuk keperluan diskusi teknis dan bukan penawaran mengikat. Nilai "
               "investasi sudah mencakup biaya material dan biaya pengerjaan. Perhitungan tidak memuat angka "
               "penghematan bahan bakar dan tidak memuat klaim jaminan kinerja. Tidak terdapat konversi mata "
               "uang asing di dalamnya.", st_small))

    render(u["out"], f"Date: {u['tanggal']}  -  {u['tag']}  -  {u['rev']}",
           f"PT SOLCOAT INDO JAYA  -  Perhitungan untuk {u['klien']}, {u['nama_aset']}",
           u["h1"], u["h2"], F)
    print(f"OK  {u['out']}")
    print(f"    area {cast+fib} m2 | {GAL} galon | investasi {rp(INV)} | perawatan {rp(TOT)}"
          f" | payback 30% gabungan {pb30:.0f} bulan")
