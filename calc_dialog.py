"""Jendela 'Hitung dengan Asumsi' — rumus calculate.solcoat.com, data awal dari hasil Riset Solcoat.

Nilai yang sudah diketahui (dari riset atau kurs otomatis) terkunci; untuk menggantinya pengguna WAJIB
mencentang kotak 'Overwrite' pada baris tersebut. Aturan validasinya ada di solcoat_research.calc_form.
"""

import logging
import queue
import threading
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

import scribd_engine as engine
from solcoat_research.calc_form import (AUTO_CONFIDENCE, FIELDS, FUEL_CHOICES, FUEL_RATE_UNITS, SCENARIO_TITLES,
                                        FieldInput, FormError, build_inputs, result_warnings)
from solcoat_research.calc_prefill import KnownValue, load_candidates
from solcoat_research.calc_report import build_calc_pdf, default_filename
from solcoat_research.calculator import calculate
from solcoat_research.area_estimate import box, cylinder
from solcoat_research.fx import fetch_usd_idr

LOGGER = logging.getLogger("momo_rescribd")
MANUAL_OPTION = "Input manual (tanpa data riset)"
SOLCOAT_GREEN = "#338B34"
SOLCOAT_GREEN_HOVER = "#1F5A20"
LOCKED_FG = "#1f2937"
EDITABLE_FG = ("#F9F9FA", "#343638")
POLL_MS = 100
FUEL_LABEL_TO_KEY = {label: key for key, label in FUEL_CHOICES.items()}


def _id_number(value: float, digits: int = 0) -> str:
    return f"{value:,.{digits}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _format_known(value) -> str:
    if isinstance(value, float):
        return _id_number(value, 0) if value.is_integer() else _id_number(value, 2)
    return FUEL_CHOICES.get(value, str(value))


class _FieldRow:
    """Satu baris: label | isian | satuan | asal nilai | Overwrite."""

    def __init__(self, dialog, parent, spec, row_index):
        self.spec = spec
        self.known: KnownValue | None = None
        self.text_var = tk.StringVar(value=spec.default)
        self.overwrite_var = tk.BooleanVar(value=False)
        font = dialog.font

        ctk.CTkLabel(parent, text=spec.label, font=(font, 11), anchor="w", width=210).grid(
            row=row_index, column=0, sticky="w", padx=(4, 8), pady=3)
        if spec.kind == "choice":
            self.widget = ctk.CTkOptionMenu(parent, values=list(FUEL_CHOICES.values()), variable=self.text_var,
                                            width=190, fg_color="#334155", button_color="#475569")
        else:
            self.widget = ctk.CTkEntry(parent, textvariable=self.text_var, width=190, font=(font, 11))
        self.widget.grid(row=row_index, column=1, sticky="w", pady=3)

        self.unit_var = tk.StringVar(value=FUEL_RATE_UNITS[0])
        self.unit_widget = None
        if spec.key == "fuel_rate":
            self.unit_widget = ctk.CTkOptionMenu(parent, values=list(FUEL_RATE_UNITS), variable=self.unit_var,
                                                 width=90, fg_color="#334155", button_color="#475569")
            self.unit_widget.grid(row=row_index, column=2, sticky="w", padx=6)
        else:
            ctk.CTkLabel(parent, text=spec.unit, font=(font, 10), text_color="#94a3b8", width=90, anchor="w").grid(
                row=row_index, column=2, sticky="w", padx=6)

        self.origin_label = ctk.CTkLabel(parent, text=spec.help, font=(font, 10), text_color="#64748b",
                                         anchor="w", justify="left", wraplength=330)
        self.origin_label.grid(row=row_index, column=3, sticky="w", padx=6)
        self.checkbox = ctk.CTkCheckBox(parent, text="Overwrite", variable=self.overwrite_var, width=90,
                                        font=(font, 10), fg_color=SOLCOAT_GREEN, hover_color=SOLCOAT_GREEN_HOVER,
                                        command=self._apply_lock)
        self.checkbox.grid(row=row_index, column=4, sticky="w", padx=4)
        self.set_known(None)

    def _default_text(self) -> str:
        return FUEL_CHOICES[self.spec.default] if self.spec.kind == "choice" else self.spec.default

    def set_known(self, known: KnownValue | None):
        self.known = known
        self.overwrite_var.set(False)
        if known is None:
            self.checkbox.grid_remove()
            self.origin_label.configure(text=self.spec.help, text_color="#64748b")
            self.text_var.set(self._default_text())
        else:
            self.checkbox.grid()
            source = {AUTO_CONFIDENCE: "kurs otomatis", "estimasi": "estimasi dimensi [A]",
                      "terverifikasi": "riset terverifikasi"}.get(known.confidence, f"riset ({known.confidence})")
            self.origin_label.configure(text=f"Diketahui dari {source}: {known.source}", text_color="#86efac")
            if self.unit_widget is not None and known.unit in FUEL_RATE_UNITS:
                self.unit_var.set(known.unit)
        self._apply_lock()

    def _apply_lock(self):
        locked = self.known is not None and not self.overwrite_var.get()
        if locked:
            self.text_var.set(_format_known(self.known.value))
        state = "disabled" if locked else "normal"
        self.widget.configure(state=state)
        if self.unit_widget is not None:
            self.unit_widget.configure(state=state)
        if isinstance(self.widget, ctk.CTkEntry):
            self.widget.configure(fg_color=LOCKED_FG if locked else EDITABLE_FG)

    def field_input(self) -> FieldInput:
        text = self.text_var.get()
        if self.spec.kind == "choice":
            text = FUEL_LABEL_TO_KEY.get(text, text)
        return FieldInput(self.spec.key, text, known=self.known, overwrite=bool(self.overwrite_var.get()))


class CalcAssumptionDialog(ctk.CTkToplevel):
    def __init__(self, app, db_path: Path | None, output_dir: Path, font_family: str):
        super().__init__(app)
        self.app, self.font, self.output_dir = app, font_family, Path(output_dir)
        self.title("Hitung dengan Asumsi — Kalkulator Solcoat")
        self.geometry("1040x780")
        self.transient(app)
        self.candidates = load_candidates(db_path) if db_path else []
        self.fx_known: dict[str, KnownValue] = {}
        self.fx_queue: queue.Queue = queue.Queue()
        self.form = self.result = None
        self._build()
        threading.Thread(target=lambda: self.fx_queue.put(fetch_usd_idr()), daemon=True).start()
        self.after(POLL_MS, self._poll_fx)

    # ------------------------------------------------------------------ layout
    def _build(self):
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(top, text="Peralatan:", font=(self.font, 12, "bold")).pack(side="left", padx=(0, 8))
        names = [MANUAL_OPTION] + [c.display_name for c in self.candidates]
        self.equipment_var = tk.StringVar(value=names[1] if len(names) > 1 else MANUAL_OPTION)
        ctk.CTkOptionMenu(top, values=names, variable=self.equipment_var, width=520, command=self._on_equipment,
                          fg_color="#334155", button_color="#475569").pack(side="left")
        hint = (f"{len(self.candidates)} peralatan dari hasil riset" if self.candidates
                else "Belum ada hasil riset — semua field diisi manual")
        ctk.CTkLabel(top, text=hint, font=(self.font, 10), text_color="#94a3b8").pack(side="left", padx=10)

        ctk.CTkLabel(self, text="Keterangan hijau = nilai sudah diketahui dan terkunci. Centang 'Overwrite' untuk "
                                "menggantinya. Skenario tetap 2,5% / 5% / 7% (kilang, petrokimia, baja).",
                     font=(self.font, 10), text_color="#94a3b8", anchor="w").pack(fill="x", padx=16)

        body = ctk.CTkScrollableFrame(self, height=380)
        body.pack(fill="both", padx=12, pady=6)
        self.rows = {spec.key: _FieldRow(self, body, spec, i) for i, spec in enumerate(FIELDS)}

        self._build_area_helper()

        self.show_price_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(self, text="Tampilkan harga per galon di PDF (angka internal — default disembunyikan)",
                        variable=self.show_price_var, font=(self.font, 11), fg_color=SOLCOAT_GREEN,
                        hover_color=SOLCOAT_GREEN_HOVER).pack(anchor="w", padx=16)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=14, pady=8)
        ctk.CTkButton(actions, text="Hitung", width=120, font=(self.font, 12, "bold"), fg_color=SOLCOAT_GREEN,
                      hover_color=SOLCOAT_GREEN_HOVER, command=self.calculate).pack(side="left", padx=(0, 8))
        self.btn_save = ctk.CTkButton(actions, text="Simpan PDF", width=120, state="disabled", fg_color="#1e293b",
                                      hover_color="#334155", border_width=1, border_color="#475569",
                                      command=self.save_pdf)
        self.btn_save.pack(side="left", padx=(0, 8))
        ctk.CTkButton(actions, text="Tutup", width=90, fg_color="#334155", hover_color="#475569",
                      command=self.destroy).pack(side="right")

        self.output = ctk.CTkTextbox(self, height=170, font=("Menlo", 11), wrap="word")
        self.output.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._on_equipment()

    def _build_area_helper(self):
        frame = ctk.CTkFrame(self, fg_color="#111827")
        frame.pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkLabel(frame, text="Hitung luas dari dimensi [A]:", font=(self.font, 11, "bold")).pack(side="left", padx=8)
        self.shape_var = tk.StringVar(value="Silinder")
        ctk.CTkOptionMenu(frame, values=["Silinder", "Kotak"], variable=self.shape_var, width=100,
                          fg_color="#334155", button_color="#475569").pack(side="left")
        self.dim_vars = {}
        for key, hint in (("a", "D / panjang (mm)"), ("b", "tinggi (mm)"), ("c", "lebar (mm, kotak)")):
            self.dim_vars[key] = tk.StringVar()
            ctk.CTkEntry(frame, textvariable=self.dim_vars[key], width=130, placeholder_text=hint).pack(side="left", padx=4)
        self.caps_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(frame, text="Tutup/atap", variable=self.caps_var, width=90, fg_color=SOLCOAT_GREEN,
                        hover_color=SOLCOAT_GREEN_HOVER).pack(side="left", padx=4)
        ctk.CTkButton(frame, text="Pakai sebagai total luas", width=170, fg_color=SOLCOAT_GREEN,
                      hover_color=SOLCOAT_GREEN_HOVER, command=self.apply_area_estimate).pack(side="left", padx=6)

    def apply_area_estimate(self):
        from solcoat_research.calc_form import parse_number
        try:
            a, b = (parse_number(self.dim_vars[k].get()) for k in ("a", "b"))
            if self.shape_var.get() == "Silinder":
                estimate = cylinder(a, b, include_ends=self.caps_var.get())
            else:
                estimate = box(a, parse_number(self.dim_vars["c"].get()), b, include_roof=self.caps_var.get())
        except ValueError as exc:
            self._set_output(f"Estimasi luas belum bisa dihitung: {exc}")
            return
        row = self.rows["area_total"]
        if row.known is not None:
            row.overwrite_var.set(True)
            row._apply_lock()
        row.text_var.set(_id_number(estimate.area_m2, 1))
        self._set_output(f"Luas estimasi [A] dipakai: {estimate.formula}\n"
                         "Ganti dengan refractory schedule / GA drawing klien bila tersedia.")

    # ------------------------------------------------------------------ data
    def _selected_candidate(self):
        return next((c for c in self.candidates if c.display_name == self.equipment_var.get()), None)

    def _on_equipment(self, _choice=None):
        candidate = self._selected_candidate()
        known = dict(candidate.known) if candidate else {}
        if candidate:
            identity = KnownValue(candidate.tag or candidate.label, "", "daftar peralatan riset", "tinggi", "")
            description = " ".join(p for p in (candidate.label, candidate.company, candidate.plant) if p)
            known.update(tag=identity, description=replace(identity, value=description))
        known.update(self.fx_known)
        for key, row in self.rows.items():
            row.set_known(known.get(key))
        warning = ("\n\nPERINGATAN: boiler batubara — skenario penghematan bahan bakar tidak berlaku (aturan Solcoat)."
                   if candidate and candidate.is_coal_fired else "")
        self._set_output("Periksa field, lalu klik Hitung." + warning)
        self.btn_save.configure(state="disabled")

    def _poll_fx(self):
        try:
            rate = self.fx_queue.get_nowait()
        except queue.Empty:
            self.after(POLL_MS, self._poll_fx)
            return
        if rate is None:
            self.rows["usd_idr"].origin_label.configure(
                text="Kurs otomatis gagal diambil — isi kurs dan tanggalnya manual (wajib).", text_color="#fbbf24")
            return
        source = f"{rate.source}, {rate.date}"
        self.fx_known = {"usd_idr": KnownValue(rate.usd_idr, "IDR", source, AUTO_CONFIDENCE, str(rate.usd_idr)),
                         "fx_date": KnownValue(rate.date, "", source, AUTO_CONFIDENCE, rate.date)}
        for key, known in self.fx_known.items():
            if not self.rows[key].overwrite_var.get():
                self.rows[key].set_known(known)

    # ------------------------------------------------------------------ actions
    def _set_output(self, text: str):
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)

    def calculate(self):
        inputs = {key: row.field_input() for key, row in self.rows.items()}
        try:
            self.form = build_inputs(inputs, fuel_rate_unit=self.rows["fuel_rate"].unit_var.get(),
                                     candidate=self._selected_candidate())
        except FormError as exc:
            self.form = self.result = None
            self.btn_save.configure(state="disabled")
            self._set_output(f"Belum bisa dihitung:\n- {exc}")
            return
        self.result = calculate(self.form.inputs)
        self._set_output(self.summary())
        self.btn_save.configure(state="normal")

    def summary(self) -> str:
        form, result = self.form, self.result
        rate, b = form.inputs.exchange_rates["IDR"], result.baseline
        lines = [
            f"Basis: {result.calculation_basis}",
            f"Energi tahunan: {_id_number(b.energy_gj)} GJ  |  Biaya energi: US$ {_id_number(b.cost_usd)}",
            f"Luas: castable {_id_number(form.inputs.area_castable, 1)} m² -> {result.gallons_castable} gal, "
            f"fiber {_id_number(form.inputs.area_fiber, 1)} m² -> {result.gallons_fiber} gal  |  total "
            f"{_id_number(result.gallons_total)} galon",
            f"Investasi material: Rp {_id_number(result.total_coating_cost_usd * rate)} "
            f"(Rp {_id_number(form.price_per_gallon_idr)}/galon, kurs {_id_number(rate)} per {form.fx_date})",
            "",
            f"{'Skenario':<26}{'Hemat Rp/tahun':>22}{'ROI %':>10}{'Payback bln':>14}",
        ]
        for sc in result.scenarios:
            roi = "-" if sc.roi_percent is None else _id_number(sc.roi_percent)
            payback = "-" if sc.payback_months is None else _id_number(sc.payback_months, 1)
            title = f"{sc.percentage:g}% {SCENARIO_TITLES.get(sc.label, '')}"
            lines.append(f"{title:<26}{_id_number(sc.financial_saving_usd * rate):>22}{roi:>10}{payback:>14}")
        notes = list(form.warnings) + result_warnings(result)
        if notes:
            lines += ["", "Catatan:"] + [f"- {n}" for n in notes]
        return "\n".join(lines)

    def save_pdf(self):
        if not (self.form and self.result):
            return
        path = self.output_dir / default_filename(self.form)
        try:
            build_calc_pdf(self.form, self.result, path, show_price_per_gallon=self.show_price_var.get())
        except OSError as exc:
            LOGGER.exception("Saving calculation PDF failed")
            messagebox.showerror("Gagal Menyimpan", f"PDF tidak bisa disimpan:\n{exc}", parent=self)
            return
        self.last_pdf = path
        engine.open_in_file_manager(str(path))
        messagebox.showinfo("Tersimpan", f"PDF kalkulasi tersimpan:\n{engine.display_path(str(path))}", parent=self)
