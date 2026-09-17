"""Jendela tab 'Analisis Lanjutan': Skor Prospek, Akurasi Ekstraksi, dan NPV Degradasi Emisivitas."""

import logging
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

import customtkinter as ctk
from openpyxl import Workbook
from reportlab.platypus import Spacer

import scribd_engine as engine
from calc_dialog import SOLCOAT_GREEN, SOLCOAT_GREEN_HOVER
from solcoat_research.accuracy import measure
from solcoat_research.calc_form import parse_number
from solcoat_research.npv import SUBSTRATE_EMISSIVITY, NpvInputs, calculate_npv
from solcoat_research.pdf_style import CW, H, P, callout, grid, kpirow, num, render, safe, st_body, st_c, st_cw
from solcoat_research.prospect import industry_prospects, pltu_prospects
from verify_dialog import _style_tree

LOGGER = logging.getLogger("momo_rescribd")


def _tree(parent, columns):
    frame = ctk.CTkFrame(parent, fg_color="#0b0f19")
    frame.pack(fill="both", expand=True)
    tree = ttk.Treeview(frame, columns=[c for c, _, _ in columns], show="headings", style="Verify.Treeview")
    for key, title, width in columns:
        tree.heading(key, text=title)
        tree.column(key, width=width, anchor="w")
    scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    return tree


def _id(value: float, digits: int = 0) -> str:
    return f"{value:,.{digits}f}".replace(",", "_").replace(".", ",").replace("_", ".")


class ProspectDialog(ctk.CTkToplevel):
    COLUMNS = (("rank", "#", 40), ("name", "Nama", 240), ("score", "Skor", 70), ("drivers", "Pendorong skor", 560))

    def __init__(self, app, db_path: Path | None, output_dir: Path, font_family: str):
        super().__init__(app)
        self.title("Skor Prospek — urut dari data, bukan ukuran")
        self.geometry("980x640")
        self.transient(app)
        self.output_dir = Path(output_dir)
        _style_tree()
        self.industry = industry_prospects(db_path) if db_path else []
        self.pltu = pltu_prospects()
        tabs = ctk.CTkTabview(self)
        tabs.pack(fill="both", expand=True, padx=10, pady=10)
        for title, rows in (("Industri (hasil riset)", self.industry), ("PLTU (PLN NP 2025)", self.pltu)):
            tree = _tree(tabs.add(title), self.COLUMNS)
            for rank, row in enumerate(rows, start=1):
                tree.insert("", "end", values=(rank, row.name, _id(row.score, 1), " · ".join(row.drivers)))
        ctk.CTkLabel(self, text="Bobot skor adalah asumsi kerja [A] untuk mengurutkan prospek, bukan angka peluang. "
                                "PLTU: SOF + (100 − EAF) + 0,5·EFOR, bonus CFB.", text_color="#94a3b8").pack(padx=10)
        ctk.CTkButton(self, text="Ekspor Excel", fg_color=SOLCOAT_GREEN, hover_color=SOLCOAT_GREEN_HOVER,
                      command=self.export).pack(pady=8)

    def export(self) -> Path:
        workbook = Workbook()
        workbook.remove(workbook.active)
        for title, rows in (("Industri", self.industry), ("PLTU", self.pltu)):
            sheet = workbook.create_sheet(title)
            sheet.append(["Peringkat", "Nama", "Skor", "Pendorong skor"])
            for rank, row in enumerate(rows, start=1):
                sheet.append([rank, row.name, row.score, "; ".join(row.drivers)])
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"Skor_Prospek_{datetime.now():%Y%m%d_%H%M}.xlsx"
        workbook.save(path)
        engine.open_in_file_manager(str(path))
        return path


class AccuracyDialog(ctk.CTkToplevel):
    COLUMNS = (("grouping", "Kelompok", 130), ("group", "Nilai", 230), ("verified", "Diverifikasi", 90),
               ("correct", "Benar", 70), ("wrong", "Salah", 70), ("precision", "Presisi", 80), ("reliable", "Andal?", 90))

    def __init__(self, app, db_path: Path | None, font_family: str):
        super().__init__(app)
        self.title("Akurasi Ekstraksi — dari verifikasi analis")
        self.geometry("860x600")
        self.transient(app)
        _style_tree()
        report = measure(db_path) if db_path else measure(Path("/nonexistent"))
        precision = "-" if report.precision is None else f"{report.precision * 100:.0f}%"
        ctk.CTkLabel(self, text=f"{report.verified} dari {report.total_facts} fakta diverifikasi · presisi keseluruhan "
                                f"{precision}", font=(font_family, 14, "bold")).pack(pady=(12, 2))
        ctk.CTkLabel(self, text=report.advice, text_color="#fbbf24", wraplength=800, justify="left").pack(padx=12)
        tree = _tree(self, self.COLUMNS)
        for row in report.rows:
            value = "-" if row.precision is None else f"{row.precision * 100:.0f}%"
            tree.insert("", "end", values=(row.grouping, row.group, row.verified, row.correct, row.wrong, value,
                                           "ya" if row.is_reliable else "sampel kurang"))
        self.report = report


class NpvDialog(ctk.CTkToplevel):
    FIELDS = (("tag", "Nama / tag alat", ""), ("investment", "Investasi material (Rp)", ""),
              ("saving", "Manfaat tahunan pada ε baru (Rp)", ""), ("rate", "Tingkat diskonto (%)", "10"),
              ("years", "Horizon (tahun)", "10"), ("eps_initial", "ε awal", "0,98"), ("eps_end", "ε akhir", "0,80"),
              ("degradation_years", "Lama degradasi (tahun)", "7"))

    def __init__(self, app, output_dir: Path, font_family: str):
        super().__init__(app)
        self.title("NPV dengan Degradasi Emisivitas")
        self.geometry("900x720")
        self.transient(app)
        self.output_dir, self.font, self.result, self.inputs = Path(output_dir), font_family, None, None
        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="x", padx=12, pady=10)
        self.vars = {}
        for index, (key, label, default) in enumerate(self.FIELDS):
            self.vars[key] = tk.StringVar(value=default)
            ctk.CTkLabel(form, text=label, width=230, anchor="w").grid(row=index // 2, column=index % 2 * 2, sticky="w")
            ctk.CTkEntry(form, textvariable=self.vars[key], width=180).grid(row=index // 2, column=index % 2 * 2 + 1,
                                                                            sticky="w", padx=(0, 12), pady=2)
        self.substrate_var = tk.StringVar(value="castable")
        ctk.CTkLabel(form, text="Substrat (ε baseline)", width=230, anchor="w").grid(row=4, column=0, sticky="w")
        ctk.CTkOptionMenu(form, values=list(SUBSTRATE_EMISSIVITY), variable=self.substrate_var, width=180,
                          fg_color="#334155", button_color="#475569").grid(row=4, column=1, sticky="w")
        ctk.CTkLabel(self, text="Manfaat tahunan bisa diambil dari 'Hitung dengan Asumsi' (hemat Rp/tahun skenario "
                                "yang dipilih). Degradasi ε ~0,98 → 0,75–0,85 dalam 6–8 tahun [A]; bertentangan dengan "
                                "klaim company profile 'stabil >0,96' — konflik dicatat di PDF.",
                     text_color="#94a3b8", wraplength=860, justify="left").pack(padx=12)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=12, pady=6)
        ctk.CTkButton(buttons, text="Hitung NPV", fg_color=SOLCOAT_GREEN, hover_color=SOLCOAT_GREEN_HOVER,
                      command=self.calculate).pack(side="left")
        self.btn_pdf = ctk.CTkButton(buttons, text="Simpan PDF", state="disabled", fg_color="#334155",
                                     hover_color="#475569", command=self.save_pdf)
        self.btn_pdf.pack(side="left", padx=8)
        self.output = ctk.CTkTextbox(self, font=("Menlo", 11), wrap="none")
        self.output.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def collect(self) -> NpvInputs:
        values = {k: self.vars[k].get().strip() for k, _, _ in self.FIELDS}
        if not values["investment"] or not values["saving"]:
            raise ValueError("Investasi dan manfaat tahunan wajib diisi")
        return NpvInputs(investment=parse_number(values["investment"]), base_annual_saving=parse_number(values["saving"]),
                         discount_rate_pct=parse_number(values["rate"]), years=int(parse_number(values["years"])),
                         eps_initial=parse_number(values["eps_initial"]), eps_end=parse_number(values["eps_end"]),
                         degradation_years=parse_number(values["degradation_years"]),
                         eps_substrate=SUBSTRATE_EMISSIVITY[self.substrate_var.get()])

    def calculate(self):
        try:
            self.inputs = self.collect()
            self.result = calculate_npv(self.inputs)
        except ValueError as exc:
            self.result = None
            self.btn_pdf.configure(state="disabled")
            self.output.delete("1.0", "end")
            self.output.insert("1.0", f"Belum bisa dihitung: {exc}")
            return
        r = self.result
        lines = [f"NPV dengan degradasi : Rp {_id(r.npv)}", f"NPV tanpa degradasi  : Rp {_id(r.npv_without_degradation)}",
                 f"IRR                  : {'-' if r.irr is None else _id(r.irr * 100, 1) + '%'}",
                 f"Payback terdiskonto  : {'tidak tercapai' if r.discounted_payback_years is None else _id(r.discounted_payback_years, 1) + ' tahun'}",
                 "", f"{'Th':>3} {'ε':>6} {'Faktor':>7} {'Manfaat Rp':>18} {'Terdiskonto Rp':>18} {'Kumulatif Rp':>18}"]
        lines += [f"{y.year:>3} {y.emissivity:>6.3f} {y.factor:>7.2f} {_id(y.saving):>18} {_id(y.discounted):>18} "
                  f"{_id(y.cumulative_discounted):>18}" for y in r.rows]
        self.output.delete("1.0", "end")
        self.output.insert("1.0", "\n".join(lines))
        self.btn_pdf.configure(state="normal")

    def save_pdf(self) -> Path | None:
        if self.result is None:
            return None
        tag = self.vars["tag"].get().strip() or "ALAT"
        path = self.output_dir / f"Analisis_NPV_{''.join(c if c.isalnum() else '_' for c in tag)}_{datetime.now():%Y%m%d_%H%M}.pdf"
        build_npv_pdf(tag, self.inputs, self.result, path)
        engine.open_in_file_manager(str(path))
        return path


def build_npv_pdf(tag: str, inp: NpvInputs, result, path: Path) -> Path:
    header = [P(safe(h), st_cw) for h in ("Tahun", "Emisivitas", "Faktor manfaat", "Manfaat (Rp)", "Terdiskonto (Rp)",
                                          "Kumulatif (Rp)")]
    rows = [header] + [[P(str(y.year), st_c), P(num(y.emissivity, 3), st_c), P(num(y.factor, 2), st_c),
                        P(num(y.saving), st_c), P(num(y.discounted), st_c), P(num(y.cumulative_discounted), st_c)]
                       for y in result.rows]
    payback = "tidak tercapai" if result.discounted_payback_years is None else f"{num(result.discounted_payback_years, 1)} tahun"
    flow = [kpirow([(f"Rp {num(result.npv / 1e9, 2)} M", "NPV dengan degradasi"),
                    (f"Rp {num(result.npv_without_degradation / 1e9, 2)} M", "NPV tanpa degradasi"),
                    ("-" if result.irr is None else f"{num(result.irr * 100, 1)}%", "IRR"),
                    (payback, "payback terdiskonto")]), Spacer(1, 6),
            H("1 - Asumsi"),
            P(safe(f"Investasi Rp {num(inp.investment)} · manfaat tahunan pada ε baru Rp {num(inp.base_annual_saving)} · "
                   f"diskonto {num(inp.discount_rate_pct, 1)}% · horizon {inp.years} tahun · ε {num(inp.eps_initial, 2)} → "
                   f"{num(inp.eps_end, 2)} dalam {num(inp.degradation_years, 1)} tahun · ε substrat {num(inp.eps_substrate, 2)}"),
              st_body),
            P(safe("Faktor manfaat = (ε tahun itu − ε substrat) / (ε awal − ε substrat), nilai tengah tahun. "
                   "Seluruh parameter degradasi adalah asumsi kerja [A]."), st_body),
            H("2 - Arus manfaat per tahun"), grid(rows, [CW * 0.1, CW * 0.14, CW * 0.14, CW * 0.2, CW * 0.2, CW * 0.22]),
            Spacer(1, 6),
            callout(safe("Konflik yang perlu disebutkan: company profile menyatakan emisivitas stabil >0,96 sepanjang "
                         "lifecycle, sedangkan model ini memakai degradasi ~0,98 → 0,75–0,85 dalam 6–8 tahun sesuai "
                         "aturan Solcoat. Pastikan asumsi disepakati sebelum dipakai di dokumen klien."))]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    render(path, hdr_r=f"{datetime.now():%d/%m/%Y}  -  {tag[:30]}  -  NPV", band=f"{tag[:80]}  -  Analisis NPV internal",
           title=safe(f"Analisis NPV dengan Degradasi Emisivitas - {tag}"),
           subtitle="Solcoat High Emissivity Coating - dokumen internal, asumsi [A]", flow=flow,
           footer="PT SOLCOAT INDO JAYA  -  Dokumen internal. Parameter degradasi adalah asumsi kerja.")
    return Path(path)
