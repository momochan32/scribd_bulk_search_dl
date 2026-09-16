"""Laporan PDF riset sumber — format hijau Solcoat untuk tim teknis & analis (dokumen internal)."""

from pathlib import Path

from reportlab.platypus import KeepTogether, Paragraph, Spacer

from . import report_data as rd
from .pdf_style import (CW, H, P, callout, grid, kpirow, num, render, safe, st_body, st_c, st_cw, st_small,
                        st_sub_h)
from .pipeline import ScanResult

FOOTER = "PT SOLCOAT INDO JAYA  -  Dokumen internal. Angka hasil ekstraksi otomatis, belum diverifikasi."
MAX_DETAIL_ROWS = 28
MAX_LOW_CONFIDENCE_ROWS = 6


def _hdr(t: str):
    return P(safe(t), st_cw)


def _c(t) -> Paragraph:
    return P(safe(t), st_c)


def _kpis(result: ScanResult, views) -> list:
    docs = rd.active_documents(result)
    pages = sum(a.page_count for a in docs)
    ocr = sum(a.ocr_pages for a in docs)
    relevant = sum(a.relevance in ("tinggi", "sedang") for a in docs)
    strong = sum(rd.CONFIDENCE_RANK[r.record.fact.confidence] >= 2 for r in result.facts)
    return [kpirow([
        (num(len(docs)), "dokumen unik dianalisis"),
        (num(pages), f"halaman dibaca ({num(ocr)} via OCR)"),
        (num(relevant), "dokumen relevan (tinggi/sedang)"),
        (num(sum(v.record.tier == "A" for v in views)), "peralatan target tier A"),
        (num(strong), "fakta keyakinan tinggi/sedang"),
    ]), Spacer(1, 6)]


def _how_to_read() -> list:
    rows = [[_hdr("Istilah"), _hdr("Arti")]] + [[P(f"<b>{a}</b>", st_c), _c(b)] for a, b in (
        ("Keyakinan tinggi", "Nilai dari blok spesifikasi 'Kunci : nilai' tepat di bawah judul peralatan."),
        ("Keyakinan sedang", "Nama peralatan disebut di kalimat yang sama dengan angkanya."),
        ("Keyakinan rendah", "Peralatan disimpulkan dari konteks terdekat. Hanya di Excel, kecuali untuk melengkapi."),
        ("Tier A / B", "A = target langsung Solcoat (berapi, hot face >= 500 °C). B = terkait (WHB, dryer, superheater, bagian)."),
        ("Sumber primer / sekunder", "Primer = laporan tahunan/keberlanjutan perusahaan. Sekunder = laporan KP mahasiswa, presentasi, makalah."),
        ("Nilai baku", "Satuan diseragamkan: °C, bar, MW, mm, m², Nm³/jam, ton/jam. Nilai asli tetap dicantumkan."),
    )]
    return [H("1 - Cara membaca laporan ini"), grid(rows, [110, CW - 110]), Spacer(1, 5), callout(
        "<b>Status seluruh angka: belum diverifikasi.</b> Tidak ada angka di laporan ini yang boleh diberi label [U] "
        "sebelum dicocokkan ke halaman sumber. Angka dari laporan KP mahasiswa diperlakukan sebagai sumber sekunder; "
        "angka OCR wajib dicek ke gambar halaman aslinya.")]


def _inventory(result: ScanResult) -> list:
    fact_counts: dict[str, int] = {}
    for row in result.facts:
        eq = row.record.fact.equipment
        if eq and eq.tier in "AB" and rd.CONFIDENCE_RANK[row.record.fact.confidence] >= 2:
            fact_counts[row.doc_path] = fact_counts.get(row.doc_path, 0) + 1
    docs = sorted(rd.active_documents(result), key=lambda a: -a.relevance_score)
    rows = [[_hdr(h) for h in ("Dokumen", "Topik", "Jenis sumber", "Hlm / OCR", "Relevansi (skor)", "Fakta alat")]]
    rows += [[_c(rd.short_doc(a.name, 46)), _c(a.topic), _c(f"{a.source_type} ({a.source_grade})"),
              _c(f"{a.page_count} / {a.ocr_pages}"), _c(f"{a.relevance} ({num(a.relevance_score)})"),
              _c(num(fact_counts.get(a.path, 0)))] for a in docs if a.relevance != "tidak relevan"]
    return [H("2 - Inventaris sumber yang relevan"), grid(rows, [168, 70, 118, 45, 70, CW - 471])]


def _coverage(views) -> list:
    tier_a = [v for v in views if v.record.tier == "A"]
    labels = [label for label, _ in rd.SOLCOAT_NEEDS]
    width = (CW - 150) / len(labels)
    rows = [[_hdr("Peralatan")] + [_hdr(label) for label in labels]]
    for v in tier_a:
        name = f"<b>{safe(v.record.label)}</b> {safe(v.record.tag)}<br/>{safe(v.record.company)} {safe(v.record.plant)}"
        rows.append([P(name, st_c)] + [P("<b>ada</b>" if ok else "-", st_c) for ok in rd.coverage(v)])
    note = P("'ada' = minimal satu fakta keyakinan tinggi/sedang. '-' = tidak ditemukan di sumber; data ini harus "
             "diminta langsung ke klien (GA drawing, refractory schedule, datasheet API 560, log operasi).", st_small)
    return [H("3 - Peta kebutuhan data Solcoat per peralatan target"), grid(rows, [150] + [width] * len(labels)),
            Spacer(1, 3), note]


def _overview(views) -> list:
    rows = [[_hdr(h) for h in ("Perusahaan / pabrik", "Peralatan", "Tier", "Parameter kunci", "Sumber")]]
    for v in views:
        docs = ", ".join(rd.short_doc(d, 24) for d in v.record.doc_names[:2])
        rows.append([_c(f"{v.record.company} {v.record.plant}".strip()), P(
            f"<b>{safe(v.record.label)}</b> {safe(v.record.tag)}", st_c), _c(v.record.tier),
            _c(rd.key_summary(v)), _c(docs)])
    return [H("4 - Ringkasan peralatan target yang ditemukan"), grid(rows, [92, 92, 24, 207, CW - 415])]


def _detail_rows(view):
    strong = [r for r in view.rows if rd.CONFIDENCE_RANK[r.record.fact.confidence] >= 2]
    weak = [r for r in view.rows if rd.CONFIDENCE_RANK[r.record.fact.confidence] < 2][:MAX_LOW_CONFIDENCE_ROWS]
    chosen = (strong + weak)[:MAX_DETAIL_ROWS]
    rows = [[_hdr(h) for h in ("Parameter", "Nilai asli", "Nilai baku", "Kualifier / komponen", "Keyakinan",
                               "Sumber", "Catatan")]]
    for row in chosen:
        f = row.record.fact
        detail = " / ".join(x for x in (f.qualifier, f.equipment.component if f.equipment else "") if x)
        rows.append([_c(f.param_label), _c(f.raw), _c(rd.fmt_std(f) if f.value_std is not None else ""),
                     _c(detail), _c(f.confidence), _c(f"{rd.source_ref(row)} ({row.record.page_method})"),
                     _c("; ".join(rd.display_flags(f, include_ocr=True))[:140])])
    return rows, len(view.rows) - len(chosen)


def _details(views) -> list:
    flow = [H("5 - Detail parameter per peralatan (dengan sumber halaman)"), P(
        "Tier A dan unit panas utama tier B (secondary reformer, WHB, superheater). Peralatan lain ada di Excel.",
        st_small)]
    for v in rd.detail_equipment(views):
        rows, hidden = _detail_rows(v)
        title = f"{v.record.label} {v.record.tag} - {v.record.company} {v.record.plant}".replace("  ", " ")
        flow.append(KeepTogether([P(safe(title), st_sub_h), grid(rows, [80, 66, 60, 70, 50, 105, CW - 431])]))
        if hidden:
            flow.append(P(f"{hidden} baris lain (keyakinan rendah) ada di Excel, sheet Fakta.", st_small))
    return flow


def _commercial(result: ScanResult) -> list:
    rows = [[_hdr(h) for h in ("Perusahaan", "Parameter", "Nilai", "Kutipan", "Sumber")]]
    rows += [[_c(r.record.company), _c(r.record.fact.param_label), _c(rd.fmt_std(r.record.fact)),
              _c(r.record.fact.snippet[:220]), _c(rd.source_ref(r))] for r in rd.commercial_rows(result)]
    return [H("6 - Indikasi energi, kapasitas, dan komersial"), grid(rows, [72, 78, 62, 208, CW - 420])]


def _strategic(result: ScanResult) -> list:
    rows = [[_hdr(h) for h in ("Kata kunci", "Kutipan", "Sumber")]]
    rows += [[_c(kw), _c(sentence), _c(src)] for kw, sentence, src in rd.strategic_rows(result)]
    return [H("7 - Konteks strategis (kutipan langsung)"), grid(rows, [70, 330, CW - 400])]


def _verification(result: ScanResult, views) -> list:
    rows = [[_hdr(h) for h in ("Peralatan / parameter", "Nilai", "Masalah", "Sumber")]]
    for r in rd.verification_rows(result, views):
        f = r.record.fact
        who = f"{f.equipment.label} {f.equipment.tag or ''} - " if f.equipment else ""
        rows.append([_c(who + f.param_label), _c(f.raw), _c("; ".join(rd.display_flags(f))[:260]), _c(rd.source_ref(r))])
    if len(rows) == 1:
        rows.append([_c("-"), _c("-"), _c("Tidak ada temuan selain penanda OCR."), _c("-")])
    return [H("8 - Perlu verifikasi sebelum dipakai"), grid(rows, [130, 70, 205, CW - 405])]


def _excluded(result: ScanResult) -> list:
    rows = [[_hdr(h) for h in ("Dokumen", "Alasan dikecualikan")]]
    rows += [[_c(rd.short_doc(d.name, 60)), _c(f"Duplikat dari {rd.short_doc(d.original, 50)} - {d.reason}")]
             for d in result.duplicates]
    rows += [[_c(rd.short_doc(a.name, 60)), _c(f"Tidak relevan untuk Solcoat ({a.source_type}); skor {num(a.relevance_score)}")]
             for a in rd.active_documents(result) if a.relevance == "tidak relevan"]
    return [H("9 - Dokumen yang dikecualikan"), grid(rows, [230, CW - 230])]


def _method() -> list:
    paragraphs = (
        "<b>Ekstraksi.</b> Setiap halaman dibaca dari text layer PDF. Halaman kosong, hasil scan, atau dengan encoding "
        "font rusak otomatis dibaca ulang dengan OCR Tesseract (bahasa Indonesia + Inggris, 300 dpi).",
        "<b>Normalisasi.</b> Ligatur yang hilang ('Esiensi' -> 'Efisiensi'), variasi satuan OCR (oC, kg/cm'G, Nm'/jam, m?), "
        "dan format angka Indonesia/Inggris diseragamkan. Angka yang bisa bermakna ganda ditandai.",
        "<b>Relasi.</b> Angka dikaitkan ke peralatan lewat tiga lapis: blok spesifikasi, kalimat yang sama, lalu konteks "
        "terdekat. Perusahaan diambil dari nama pabrik (mis. Kaltim-3 -> Pupuk Kaltim) atau topik folder.",
        "<b>Batasan.</b> Tabel yang dipindai tanpa garis, gambar, grafik, dan GA drawing tidak terbaca sebagai angka. "
        "Relasi lintas halaman lemah. Script tidak memahami makna: 'desain' vs 'aktual' hanya dikenali dari kata kunci.",
        "<b>Data lengkap.</b> Excel pendamping memuat seluruh fakta (termasuk keyakinan rendah), dan research.db "
        "menyediakan pencarian teks penuh per halaman: <font face='Courier'>python -m solcoat_research search</font>.",
    )
    return [H("10 - Metodologi dan batasan")] + [P(p, st_body) for p in paragraphs]


def build_pdf(result: ScanResult, path: Path) -> Path:
    views = rd.target_equipment(result)
    date = result.created_at.strftime("%d/%m/%Y")
    topics = sorted({a.topic for a in rd.active_documents(result)})
    entity = result.config.title or ", ".join(topics)
    flow = (_kpis(result, views) + _how_to_read() + _inventory(result) + _coverage(views) + _overview(views)
            + _details(views) + _commercial(result) + _strategic(result) + _verification(result, views)
            + _excluded(result) + _method())
    render(
        path, hdr_r=f"{date}  -  RISET-SUMBER  -  Rev 0", band=f"{entity[:90]}  -  Riset internal tim teknis & analis",
        title="Laporan Riset Sumber PDF",
        subtitle=safe(f"Folder: {result.config.input_dir.name} ({', '.join(topics)}) - dipindai {date} - "
                      "ekstraksi otomatis tanpa AI (text layer + OCR)"),
        flow=flow, footer=FOOTER,
    )
    return path
