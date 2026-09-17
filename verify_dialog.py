"""Jendela 'Verifikasi Fakta': cocokkan angka hasil riset ke halaman sumbernya, lalu tandai benar/salah + [U]/[V]/[A].

Verifikasi tersimpan permanen di research.db dan otomatis dipakai oleh laporan (setelah riset diulang) dan
oleh kalkulator 'Hitung dengan Asumsi' (langsung).
"""

import io
import logging
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import messagebox, ttk

import customtkinter as ctk
from PIL import Image

import scribd_engine as engine
from solcoat_research.calc_form import parse_number
from solcoat_research.verification import (LABEL_MEANING, LABELS, UNVERIFIED, Verification, clear_verification,
                                           list_facts, render_page, save_verification)

LOGGER = logging.getLogger("momo_rescribd")
SOLCOAT_GREEN = "#338B34"
SOLCOAT_GREEN_HOVER = "#1F5A20"
PREVIEW_WIDTH = 470
STATUS_FILTERS = {"Belum diverifikasi": UNVERIFIED, "Benar": "benar", "Salah": "salah", "Semua": None}
ALL_EQUIPMENT = "Peralatan target (tier A/B)"
EVERYTHING = "Semua fakta (termasuk tanpa alat)"
COLUMNS = (("status", "Status", 120), ("equipment", "Peralatan", 170), ("param", "Parameter", 150),
           ("value", "Nilai", 110), ("confidence", "Keyakinan", 72), ("source", "Sumber", 190))


def _style_tree() -> None:
    style = ttk.Style()
    style.configure("Verify.Treeview", background="#111827", fieldbackground="#111827", foreground="#e2e8f0",
                    rowheight=24, borderwidth=0)
    style.map("Verify.Treeview", background=[("selected", SOLCOAT_GREEN)], foreground=[("selected", "white")])
    style.configure("Verify.Treeview.Heading", background=SOLCOAT_GREEN_HOVER, foreground="white", relief="flat")


def status_text(fact) -> str:
    v = fact.verification
    if v is None:
        return UNVERIFIED
    return f"{v.status} [{v.label}]" + (" +koreksi" if v.corrected_value is not None else "")


class VerifyDialog(ctk.CTkToplevel):
    def __init__(self, app, db_path: Path, font_family: str):
        super().__init__(app)
        self.app, self.db_path, self.font = app, Path(db_path), font_family
        self.title("Verifikasi Fakta — Riset Solcoat")
        self.geometry("1280x820")
        self.transient(app)
        self.facts, self.by_iid, self.current = [], {}, None
        self.preview_image = None
        _style_tree()
        self._build()
        self.refresh()

    # ------------------------------------------------------------------ layout
    def _build(self):
        filters = ctk.CTkFrame(self, fg_color="transparent")
        filters.pack(fill="x", padx=12, pady=(10, 4))
        self.scope_var = tk.StringVar(value=ALL_EQUIPMENT)
        ctk.CTkOptionMenu(filters, values=[ALL_EQUIPMENT, EVERYTHING], variable=self.scope_var, width=240,
                          command=lambda _: self.refresh(), fg_color="#334155", button_color="#475569").pack(side="left")
        self.status_var = tk.StringVar(value="Belum diverifikasi")
        ctk.CTkOptionMenu(filters, values=list(STATUS_FILTERS), variable=self.status_var, width=170,
                          command=lambda _: self.refresh(), fg_color="#334155", button_color="#475569").pack(
            side="left", padx=8)
        self.low_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(filters, text="Termasuk keyakinan rendah", variable=self.low_var, command=self.refresh,
                        fg_color=SOLCOAT_GREEN, hover_color=SOLCOAT_GREEN_HOVER, font=(self.font, 11)).pack(side="left")
        self.search_var = tk.StringVar()
        entry = ctk.CTkEntry(filters, textvariable=self.search_var, width=200, placeholder_text="Cari parameter/dokumen")
        entry.pack(side="left", padx=8)
        entry.bind("<Return>", lambda _: self.refresh())
        self.count_label = ctk.CTkLabel(filters, text="", font=(self.font, 10), text_color="#94a3b8")
        self.count_label.pack(side="left", padx=6)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        left = ctk.CTkFrame(body, fg_color="#0b0f19")
        left.pack(side="left", fill="both", expand=True)
        self.tree = ttk.Treeview(left, columns=[c[0] for c in COLUMNS], show="headings", style="Verify.Treeview")
        for key, title, width in COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="w")
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        right = ctk.CTkScrollableFrame(body, width=PREVIEW_WIDTH + 20, fg_color="#111827")
        right.pack(side="right", fill="y", padx=(10, 0))
        self._build_detail(right)

    def _build_detail(self, parent):
        self.detail_title = ctk.CTkLabel(parent, text="Pilih fakta di tabel", font=(self.font, 13, "bold"),
                                         anchor="w", justify="left", wraplength=PREVIEW_WIDTH)
        self.detail_title.pack(fill="x", pady=(4, 2))
        self.detail_meta = ctk.CTkLabel(parent, text="", font=(self.font, 10), text_color="#94a3b8", anchor="w",
                                        justify="left", wraplength=PREVIEW_WIDTH)
        self.detail_meta.pack(fill="x")
        self.snippet = ctk.CTkTextbox(parent, height=70, wrap="word", font=(self.font, 11))
        self.snippet.pack(fill="x", pady=6)

        form = ctk.CTkFrame(parent, fg_color="transparent")
        form.pack(fill="x", pady=4)
        self.decision_var = tk.StringVar(value="benar")
        ctk.CTkSegmentedButton(form, values=["benar", "salah"], variable=self.decision_var,
                               selected_color=SOLCOAT_GREEN, selected_hover_color=SOLCOAT_GREEN_HOVER).pack(side="left")
        self.label_var = tk.StringVar(value="U")
        ctk.CTkSegmentedButton(form, values=list(LABELS), variable=self.label_var, command=self._show_label_meaning,
                               selected_color=SOLCOAT_GREEN, selected_hover_color=SOLCOAT_GREEN_HOVER).pack(
            side="left", padx=10)
        self.label_meaning = ctk.CTkLabel(form, text=LABEL_MEANING["U"], font=(self.font, 10), text_color="#94a3b8")
        self.label_meaning.pack(side="left")

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=4)
        self.corrected_label = ctk.CTkLabel(row, text="Koreksi nilai (opsional):", font=(self.font, 11))
        self.corrected_label.pack(side="left")
        self.corrected_var = tk.StringVar()
        ctk.CTkEntry(row, textvariable=self.corrected_var, width=120).pack(side="left", padx=6)
        self.note_var = tk.StringVar()
        ctk.CTkEntry(parent, textvariable=self.note_var, placeholder_text="Catatan verifikasi (opsional)").pack(fill="x")

        buttons = ctk.CTkFrame(parent, fg_color="transparent")
        buttons.pack(fill="x", pady=8)
        ctk.CTkButton(buttons, text="Simpan & berikutnya", width=150, fg_color=SOLCOAT_GREEN,
                      hover_color=SOLCOAT_GREEN_HOVER, command=self.save).pack(side="left")
        ctk.CTkButton(buttons, text="Hapus verifikasi", width=120, fg_color="#334155", hover_color="#475569",
                      command=self.clear).pack(side="left", padx=6)
        ctk.CTkButton(buttons, text="Buka PDF", width=90, fg_color="#334155", hover_color="#475569",
                      command=self.open_pdf).pack(side="left")

        self.preview_note = ctk.CTkLabel(parent, text="", font=(self.font, 10), text_color="#fbbf24", anchor="w",
                                         justify="left", wraplength=PREVIEW_WIDTH)
        self.preview_note.pack(fill="x")
        self.preview = ctk.CTkLabel(parent, text="")
        self.preview.pack(pady=4)
        ctk.CTkLabel(parent, text="Laporan PDF/Excel memakai verifikasi setelah 'Mulai Riset' dijalankan lagi "
                                  "(±15 detik dari cache). Kalkulator langsung memakainya.",
                     font=(self.font, 10), text_color="#64748b", wraplength=PREVIEW_WIDTH, justify="left").pack(fill="x")

    # ------------------------------------------------------------------ data
    def refresh(self):
        self.facts = list_facts(self.db_path, target_only=self.scope_var.get() == ALL_EQUIPMENT,
                                status=STATUS_FILTERS[self.status_var.get()], include_low=self.low_var.get(),
                                search=self.search_var.get().strip())
        self.tree.delete(*self.tree.get_children())
        self.by_iid = {}
        for fact in self.facts:
            iid = self.tree.insert("", "end", values=(
                status_text(fact), fact.equipment, fact.param_label, fact.raw, fact.confidence,
                f"{fact.doc_name[:34]} h.{fact.page_no}"))
            self.by_iid[iid] = fact
        self.count_label.configure(text=f"{len(self.facts)} fakta")
        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])
            self.tree.see(children[0])

    def _show_label_meaning(self, label):
        self.label_meaning.configure(text=LABEL_MEANING[label])

    def _on_select(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            return
        fact = self.current = self.by_iid[selection[0]]
        flags = f"\nCatatan ekstraksi: {fact.flags}" if fact.flags not in ("", "[]") else ""
        self.detail_title.configure(text=f"{fact.param_label}: {fact.raw}")
        self.detail_meta.configure(text=f"{fact.equipment} · {fact.company}\n{fact.doc_name} — halaman {fact.page_no} "
                                        f"({fact.page_method}) · keyakinan {fact.confidence}{flags}")
        self.snippet.delete("1.0", "end")
        self.snippet.insert("1.0", fact.snippet)
        v = fact.verification
        self.decision_var.set(v.status if v else "benar")
        self.label_var.set(v.label if v else "U")
        self._show_label_meaning(self.label_var.get())
        self.corrected_var.set("" if not v or v.corrected_value is None else f"{v.corrected_value:g}")
        self.note_var.set(v.note if v else "")
        self.corrected_label.configure(text=f"Koreksi nilai ({fact.std_unit or 'satuan baku'}):")
        self._render_preview(fact)

    def _render_preview(self, fact):
        try:
            png, found = render_page(fact.doc_path, fact.page_no, fact.raw)
        except (OSError, ValueError, RuntimeError) as exc:
            self.preview.configure(image=None, text=f"Pratinjau tidak tersedia: {exc}")
            self.preview_note.configure(text="")
            return
        image = Image.open(io.BytesIO(png))
        height = int(image.height * PREVIEW_WIDTH / image.width)
        self.preview_image = ctk.CTkImage(light_image=image, dark_image=image, size=(PREVIEW_WIDTH, height))
        self.preview.configure(image=self.preview_image, text="")
        self.preview_note.configure(text="" if found else
                                    "Nilai tidak ditemukan di text layer halaman ini (mis. halaman hasil OCR) — "
                                    "cocokkan manual dengan gambar halaman.")

    # ------------------------------------------------------------------ actions
    def _select_next(self):
        selection, children = self.tree.selection(), self.tree.get_children()
        if not selection or not children:
            return
        index = children.index(selection[0])
        if index + 1 < len(children):
            self.tree.selection_set(children[index + 1])
            self.tree.see(children[index + 1])

    def save(self):
        if self.current is None:
            return
        corrected_text = self.corrected_var.get().strip()
        try:
            corrected = parse_number(corrected_text) if corrected_text else None
            verification = Verification(self.decision_var.get(), self.label_var.get(), corrected, self.note_var.get())
            saved = save_verification(self.db_path, self.current, verification)
        except ValueError as exc:
            messagebox.showwarning("Belum Bisa Disimpan", str(exc), parent=self)
            return
        self._update_row(saved)
        self._select_next()

    def clear(self):
        if self.current is None:
            return
        clear_verification(self.db_path, self.current.fingerprint)
        self._update_row(None)

    def _update_row(self, verification):
        selection = self.tree.selection()
        if not selection:
            return
        iid = selection[0]
        updated = replace(self.by_iid[iid], verification=verification)
        self.by_iid[iid] = self.current = updated
        values = list(self.tree.item(iid, "values"))
        values[0] = status_text(updated)
        self.tree.item(iid, values=values)

    def open_pdf(self):
        if self.current and not engine.open_in_file_manager(self.current.doc_path):
            messagebox.showinfo("Informasi", f"PDF tidak ditemukan:\n{self.current.doc_path}", parent=self)
