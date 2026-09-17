"""Jendela 'Mode PLTU' — laporan avoided cost 9 bagian (format baku), bukan skenario penghematan bahan bakar.

Data kinerja unit PLN NP diambil dari tabel Laporan Tahunan 2025 dan terkunci; menggantinya wajib lewat
kotak 'Overwrite' (aturan yang sama dengan kalkulator). Checklist §5 dijalankan sebelum PDF dibuat.
"""

import logging
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

import scribd_engine as engine
from calc_dialog import SOLCOAT_GREEN, SOLCOAT_GREEN_HOVER, FieldRow
from solcoat_research.calc_form import PRIMARY_CONFIDENCE, FieldSpec, FormError, parse_number, resolve_field
from solcoat_research.calc_prefill import KnownValue
from solcoat_research.pltu.pln_data import MANUAL_UNIT, SOURCE as PLN_SOURCE, UNIT_NOTES, UNITS
from solcoat_research.pltu.unit_builder import (DEFAULT_AREA_SOURCE, DEFAULT_STREAMS_TEXT, Performance,
                                                PltuFormError, PltuInputs, checklist, generate_pdf, id_num,
                                                lining_stream, parse_streams, parse_zones, summary)

LOGGER = logging.getLogger("momo_rescribd")
PERFORMANCE_FIELDS = (
    FieldSpec("eaf", "EAF 2025", "%", "number", required=True, minimum=1, maximum=99.99),
    FieldSpec("sof", "SOF 2025", "%", "number", minimum=0, maximum=100),
    FieldSpec("efor", "EFOR 2025", "%", "number", required=True, minimum=0, maximum=100),
    FieldSpec("nphr", "NPHR 2025", "kCal/kWh", "number", required=True, minimum=1),
    FieldSpec("production_gwh", "Produksi 2025", "GWh", "number", minimum=0),
    FieldSpec("dtp_mw", "Daya terpasang UP", "MW", "number", required=True, minimum=0.1),
)
IDENTITY_FIELDS = (("tag", "Tag unit", ""), ("rev", "Revisi", "Rev 0"), ("client", "Klien", "PT PLN (Persero)"),
                   ("asset_name", "Nama aset", ""), ("location", "Lokasi", ""), ("oem", "OEM boiler", ""),
                   ("cod", "COD", ""), ("capacity_mw", "Kapasitas unit (MW)", ""))


class PltuDialog(ctk.CTkToplevel):
    def __init__(self, app, output_dir: Path, font_family: str):
        super().__init__(app)
        self.app, self.output_dir, self.font = app, Path(output_dir), font_family
        self.title("Mode PLTU — Biaya Perawatan yang Dihindari")
        self.geometry("1060x860")
        self.transient(app)
        self.vars: dict[str, tk.StringVar] = {}
        self.last_pdf = None
        self._build()
        self._on_unit()

    # ------------------------------------------------------------------ layout
    def _section(self, parent, title):
        ctk.CTkLabel(parent, text=title, font=(self.font, 13, "bold"), text_color="#86efac", anchor="w").pack(
            fill="x", pady=(10, 4))

    def _entry_grid(self, parent, fields):
        grid = ctk.CTkFrame(parent, fg_color="transparent")
        grid.pack(fill="x")
        for index, (key, label, default) in enumerate(fields):
            self.vars[key] = tk.StringVar(value=default)
            ctk.CTkLabel(grid, text=label, width=170, anchor="w").grid(row=index // 2, column=index % 2 * 2, sticky="w")
            ctk.CTkEntry(grid, textvariable=self.vars[key], width=300).grid(
                row=index // 2, column=index % 2 * 2 + 1, sticky="w", padx=(0, 16), pady=2)
        return grid

    def _textbox(self, parent, label, text, height=90):
        ctk.CTkLabel(parent, text=label, anchor="w", font=(self.font, 11)).pack(fill="x")
        box = ctk.CTkTextbox(parent, height=height, wrap="none", font=("Menlo", 11))
        box.pack(fill="x", pady=(0, 6))
        box.insert("1.0", text)
        return box

    def _build(self):
        body = ctk.CTkScrollableFrame(self)
        body.pack(fill="both", expand=True, padx=12, pady=(10, 4))
        ctk.CTkLabel(body, text="Skenario PLTU = pengurangan frekuensi kejadian 15/30/50% (avoided cost). Tidak ada "
                                "angka penghematan bahan bakar. Waterwall otomatis masuk tabel di luar lingkup.",
                     font=(self.font, 10), text_color="#94a3b8", anchor="w", justify="left").pack(fill="x")
        self._build_identity(body)
        self._build_performance(body)
        self._build_scope(body)
        self._build_streams(body)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=12, pady=6)
        ctk.CTkButton(actions, text="Periksa checklist", width=140, fg_color="#334155", hover_color="#475569",
                      command=self.check).pack(side="left")
        ctk.CTkButton(actions, text="Buat PDF PLTU", width=140, fg_color=SOLCOAT_GREEN, hover_color=SOLCOAT_GREEN_HOVER,
                      font=(self.font, 12, "bold"), command=self.generate).pack(side="left", padx=8)
        ctk.CTkButton(actions, text="Tutup", width=90, fg_color="#334155", hover_color="#475569",
                      command=self.destroy).pack(side="right")
        self.output = ctk.CTkTextbox(self, height=140, wrap="word", font=("Menlo", 11))
        self.output.pack(fill="x", padx=12, pady=(0, 10))

    def _build_identity(self, body):
        self._section(body, "1 · Identitas unit")
        grid = self._entry_grid(body, IDENTITY_FIELDS)
        self.boiler_var = tk.StringVar(value="CFB")
        ctk.CTkLabel(grid, text="Kelas boiler", width=170, anchor="w").grid(row=4, column=0, sticky="w")
        ctk.CTkOptionMenu(grid, values=["CFB", "PC"], variable=self.boiler_var, width=120, fg_color="#334155",
                          button_color="#475569").grid(row=4, column=1, sticky="w")

    def _build_performance(self, body):
        self._section(body, "2 · Kinerja operasi 2025 (Laporan Tahunan PLN NP)")
        unit_row = ctk.CTkFrame(body, fg_color="transparent")
        unit_row.pack(fill="x")
        self.unit_var = tk.StringVar(value="UP Nagan Raya")
        ctk.CTkOptionMenu(unit_row, values=list(UNITS) + [MANUAL_UNIT], variable=self.unit_var, width=260,
                          command=lambda _: self._on_unit(), fg_color="#334155", button_color="#475569").pack(side="left")
        self.unit_note = ctk.CTkLabel(unit_row, text="", font=(self.font, 10), text_color="#fbbf24", anchor="w",
                                      justify="left", wraplength=650)
        self.unit_note.pack(side="left", padx=10)
        perf = ctk.CTkFrame(body, fg_color="transparent")
        perf.pack(fill="x")
        self.perf_rows = {spec.key: FieldRow(self, perf, spec, i) for i, spec in enumerate(PERFORMANCE_FIELDS)}

    def _build_scope(self, body):
        self._section(body, "3 · Lingkup & nilai investasi")
        self.cast_box = self._textbox(body, "Zona castable — satu per baris: Nama zona ; luas m2", "")
        self.fib_box = self._textbox(body, "Zona ceramic fiber — satu per baris: Nama zona ; luas m2", "", height=50)
        self._entry_grid(body, (("area_source", "Sumber luas", DEFAULT_AREA_SOURCE),
                                ("price_per_gallon", "Harga per galon (Rp)", "85.000.000"),
                                ("gallon_override", "Override galon (opsional)", "")))
        self.show_price_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(body, text="Tampilkan harga per galon di PDF", variable=self.show_price_var,
                        fg_color=SOLCOAT_GREEN, hover_color=SOLCOAT_GREEN_HOVER).pack(anchor="w", pady=4)

    def _build_streams(self, body):
        self._section(body, "4 · Biaya perawatan yang dihindari (asumsi [A])")
        self.stream_box = self._textbox(
            body, "Satu aliran per baris: Nama | dasar perhitungan | nilai tahunan Rp | ya/tidak (ikut skala interval)",
            DEFAULT_STREAMS_TEXT, height=110)
        helper = ctk.CTkFrame(body, fg_color="transparent")
        helper.pack(fill="x")
        ctk.CTkLabel(helper, text="Tambah aliran lining:", width=170, anchor="w").pack(side="left")
        for key, hint in (("lining_area", "luas m2"), ("lining_thickness", "tebal m"), ("lining_interval", "interval tahun")):
            self.vars[key] = tk.StringVar()
            ctk.CTkEntry(helper, textvariable=self.vars[key], width=110, placeholder_text=hint).pack(side="left", padx=3)
        ctk.CTkButton(helper, text="Tambah", width=80, fg_color="#334155", hover_color="#475569",
                      command=self.add_lining).pack(side="left", padx=6)
        self._entry_grid(body, (("interval_label", "Ringkasan interval", "coal nozzle 3 tahun"),
                                ("component_price_source", "Sumber harga komponen", ""),
                                ("unit_spec_source", "Sumber spesifikasi unit", "")))

    # ------------------------------------------------------------------ data
    def _on_unit(self):
        unit = UNITS.get(self.unit_var.get())
        values = {} if unit is None else {"eaf": unit.eaf, "sof": unit.sof, "efor": unit.efor, "nphr": unit.nphr,
                                          "production_gwh": unit.production_gwh, "dtp_mw": unit.dtp_mw}
        for key, row in self.perf_rows.items():
            value = values.get(key)
            row.set_known(None if value is None else
                          KnownValue(float(value), row.spec.unit, PLN_SOURCE, PRIMARY_CONFIDENCE, str(value)))
            if value is None:
                row.text_var.set("")
        note = UNIT_NOTES.get(self.unit_var.get(), "")
        self.unit_note.configure(text="Isi kinerja dari data unit klien. Asumsi EAF 85% dilarang." if unit is None else note)

    def _text(self, key: str) -> str:
        return self.vars[key].get().strip()

    def _performance(self) -> Performance:
        resolved = {spec.key: resolve_field(spec, self.perf_rows[spec.key].field_input()) for spec in PERFORMANCE_FIELDS}

        def value(key):
            return None if resolved[key].value is None else float(resolved[key].value)

        overwritten = any(v.origin == "overwrite pengguna" for v in resolved.values())
        return Performance(value("eaf"), value("sof"), value("efor"), value("nphr"), value("production_gwh"),
                           value("dtp_mw"), overwritten=overwritten)

    def collect(self) -> PltuInputs:
        override = self._text("gallon_override")
        return PltuInputs(
            tag=self._text("tag"), rev=self._text("rev"), client=self._text("client"),
            asset_name=self._text("asset_name"), location=self._text("location"), up=self.unit_var.get(),
            capacity_mw=parse_number(self._text("capacity_mw") or "0"), boiler_class=self.boiler_var.get(),
            oem=self._text("oem"), cod=self._text("cod"), performance=self._performance(),
            castable_zones=parse_zones(self.cast_box.get("1.0", "end"), "castable"),
            fiber_zones=parse_zones(self.fib_box.get("1.0", "end"), "ceramic fiber"),
            streams=parse_streams(self.stream_box.get("1.0", "end")),
            interval_label=self._text("interval_label"), component_price_source=self._text("component_price_source"),
            unit_spec_source=self._text("unit_spec_source"),
            area_source=self._text("area_source") or DEFAULT_AREA_SOURCE,
            price_per_gallon=parse_number(self._text("price_per_gallon")),
            gallon_override=int(parse_number(override)) if override else None,
            show_price_per_gallon=self.show_price_var.get(),
        )

    def _set_output(self, text: str):
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)

    # ------------------------------------------------------------------ actions
    def check(self) -> tuple[PltuInputs | None, list[str]]:
        try:
            inputs = self.collect()
        except (PltuFormError, FormError, ValueError) as exc:
            self._set_output(f"Belum bisa diproses:\n- {exc}")
            return None, [str(exc)]
        errors, warnings = checklist(inputs)
        lines = [f"GAGAL: {e}" for e in errors]
        if not errors:
            stats = summary(inputs)
            payback = stats["payback_30_months"]
            lines.append(f"Area {id_num(stats['area_m2'], 0)} m2 · {id_num(stats['gallons'], 0)} galon · investasi "
                         f"Rp {id_num(stats['investment'], 0)} · perawatan Rp {id_num(stats['maintenance'], 0)}/th · "
                         f"payback 30% gabungan {id_num(payback, 0) if payback else '-'} bulan")
        lines += [f"Perhatian: {w}" for w in warnings]
        self._set_output("\n".join(lines))
        return inputs, errors

    def add_lining(self):
        try:
            stream = lining_stream(*(parse_number(self._text(k))
                                     for k in ("lining_area", "lining_thickness", "lining_interval")))
        except (PltuFormError, ValueError) as exc:
            self._set_output(f"Aliran lining belum bisa ditambahkan: {exc}")
            return
        line = f"{stream.name} | {stream.basis} | {round(stream.annual_value)} | ya"
        current = self.stream_box.get("1.0", "end").rstrip()
        self.stream_box.delete("1.0", "end")
        self.stream_box.insert("1.0", f"{current}\n{line}" if current else line)

    def generate(self):
        inputs, errors = self.check()
        if inputs is None or errors:
            return None
        try:
            path = generate_pdf(inputs, self.output_dir)
        except (OSError, PltuFormError) as exc:
            LOGGER.exception("PLTU PDF generation failed")
            messagebox.showerror("Gagal Membuat PDF", str(exc), parent=self)
            return None
        self.last_pdf = path
        self._set_output(self.output.get("1.0", "end").rstrip() + f"\n\nPDF tersimpan: {engine.display_path(str(path))}")
        engine.open_in_file_manager(str(path))
        return path
