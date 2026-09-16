"""Tab "Riset Solcoat" untuk Momo Rescribd.

Membaca PDF hasil unduhan (text layer + OCR), menautkan angka ke peralatan, lalu menyusun laporan PDF
dan Excel untuk tim teknis & analis Solcoat. Logika riset ada di research/solcoat_research; modul ini
hanya UI dan thread pekerja.
"""

import logging
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

import scribd_engine as engine

_RESEARCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "research")
if os.path.isdir(_RESEARCH_DIR) and _RESEARCH_DIR not in sys.path:
    sys.path.insert(0, _RESEARCH_DIR)

LOGGER = logging.getLogger("momo_rescribd")

TAB_NAME = "Riset Solcoat"
SOLCOAT_GREEN = "#338B34"
SOLCOAT_GREEN_HOVER = "#1F5A20"
MISSING_DEPS_MESSAGE = (
    "Fitur Riset Solcoat membutuhkan paket tambahan (pymupdf, reportlab, openpyxl, pyyaml).\n\n"
    "Jalankan: pip install -r requirements.txt"
)


class ResearchPanel:
    def __init__(self, app, tab, font_family):
        self.app = app
        self.font = font_family
        self.source_var = tk.StringVar(value=app.base_folder_var.get())
        self.output_var = tk.StringVar(value="")
        self.ocr_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Pilih folder berisi PDF hasil unduhan, lalu klik Mulai Riset.")
        self.log_queue = queue.Queue()
        # Tk is not thread-safe: the worker never touches widgets, it queues UI updates
        # that poll() applies on the main thread.
        self.ui_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = None
        self.outputs = None
        self._build(tab)

    # ------------------------------------------------------------------ UI
    def _folder_row(self, tab, label, variable, placeholder):
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(row, text=label, font=(self.font, 11), text_color="#cbd5e1", width=120, anchor="w").pack(side="left")
        ctk.CTkEntry(row, textvariable=variable, placeholder_text=placeholder, font=(self.font, 11), height=30).pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            row, text="Pilih Folder...", width=100, height=30, font=(self.font, 11), fg_color="#334155",
            hover_color="#475569", command=lambda: self._browse(variable),
        ).pack(side="right")

    def _button(self, parent, text, command, width=120, primary=False, state="normal"):
        return ctk.CTkButton(
            parent, text=text, width=width, height=32, state=state, command=command,
            font=(self.font, 11, "bold" if primary else "normal"),
            fg_color=SOLCOAT_GREEN if primary else "#1e293b",
            hover_color=SOLCOAT_GREEN_HOVER if primary else "#334155",
            border_width=0 if primary else 1, border_color="#475569",
        )

    def _build(self, tab):
        ctk.CTkLabel(
            tab, text="Riset sumber PDF untuk tim teknis & analis Solcoat (tanpa AI):",
            font=(self.font, 11, "bold"), text_color="#cbd5e1",
        ).pack(anchor="w", pady=(4, 6))
        self._folder_row(tab, "Folder PDF sumber:", self.source_var, "Folder hasil unduhan, mis. Downloads/Momo_Rescribd")
        self._folder_row(tab, "Folder laporan:", self.output_var, "Kosongkan: otomatis <folder sumber>_Riset_Solcoat")

        options = ctk.CTkFrame(tab, fg_color="transparent")
        options.pack(fill="x", pady=(0, 8))
        ctk.CTkCheckBox(
            options, text="Baca halaman scan dengan OCR (data bahasa ±5 MB diunduh otomatis saat pertama)",
            variable=self.ocr_var, font=(self.font, 11), fg_color=SOLCOAT_GREEN, hover_color=SOLCOAT_GREEN_HOVER,
        ).pack(side="left")

        actions = ctk.CTkFrame(tab, fg_color="transparent")
        actions.pack(fill="x", pady=(0, 6))
        self.btn_start = self._button(actions, "Mulai Riset", self.start, width=130, primary=True)
        self.btn_start.pack(side="left", padx=(0, 8))
        self.btn_stop = self._button(actions, "Hentikan", self.stop, width=90, state="disabled")
        self.btn_stop.pack(side="left", padx=(0, 16))
        self.btn_pdf = self._button(actions, "Buka Laporan PDF", lambda: self._open("pdf"), state="disabled")
        self.btn_pdf.pack(side="left", padx=(0, 8))
        self.btn_xlsx = self._button(actions, "Buka Excel", lambda: self._open("xlsx"), width=100, state="disabled")
        self.btn_xlsx.pack(side="left", padx=(0, 8))
        self.btn_folder = self._button(actions, "Buka Folder Laporan", lambda: self._open("folder"), state="disabled")
        self.btn_folder.pack(side="left")

        ctk.CTkLabel(tab, textvariable=self.status_var, font=(self.font, 10), text_color="#64748b",
                     anchor="w", justify="left").pack(anchor="w")

    def _browse(self, variable):
        self.app.update_idletasks()
        initial = variable.get().strip() or self.source_var.get().strip() or self.app.base_folder_var.get()
        chosen = filedialog.askdirectory(parent=self.app, title="Pilih Folder", initialdir=os.path.expanduser(initial))
        if chosen:
            variable.set(chosen)

    # ------------------------------------------------------------ actions
    def is_running(self):
        return bool(self.thread and self.thread.is_alive())

    def start(self):
        if self.is_running():
            return
        source = os.path.expanduser(self.source_var.get().strip())
        if not source or not os.path.isdir(source):
            messagebox.showwarning("Peringatan", f"Folder PDF sumber tidak ditemukan:\n{source or '(kosong)'}")
            return
        try:
            from solcoat_research.runner import run_research  # noqa: F401  (cek dependensi sebelum thread jalan)
        except ImportError as exc:
            LOGGER.error("Research dependencies missing: %s", exc)
            messagebox.showerror("Paket Belum Terpasang", f"{MISSING_DEPS_MESSAGE}\n\nDetail: {exc}")
            return

        self.app._ensure_solo_tab(TAB_NAME)
        self.stop_event.clear()
        self.outputs = None
        self._set_running(True, "Riset berjalan… progres tampil di konsol tab 'Riset Solcoat'.")
        output = os.path.expanduser(self.output_var.get().strip()) or None
        self.thread = threading.Thread(target=self._worker, args=(source, output, self.ocr_var.get()), daemon=True)
        self.thread.start()
        self.app._update_global_ui_state()

    def stop(self):
        if self.is_running():
            self.stop_event.set()
            self._log("[STOP] Menghentikan riset setelah langkah yang sedang berjalan…")
            self.btn_stop.configure(state="disabled", text="Menghentikan")

    def poll(self):
        """Dipanggil loop polling GUI (thread utama): tulis log dan terapkan pembaruan UI dari pekerja."""
        textbox = self.app.active_console_tabs.get(TAB_NAME)
        if textbox is not None and not self.log_queue.empty():
            while not self.log_queue.empty():
                try:
                    textbox.insert("end", self.log_queue.get_nowait())
                except queue.Empty:
                    break
            textbox.see("end")
        while not self.ui_queue.empty():
            try:
                self.ui_queue.get_nowait()()
            except queue.Empty:
                break

    def _log(self, message):
        self.log_queue.put(f"{message}\n")

    def _set_running(self, running, status):
        self.status_var.set(status)
        self.btn_start.configure(state="disabled" if running else "normal",
                                 fg_color="#475569" if running else SOLCOAT_GREEN)
        self.btn_stop.configure(state="normal" if running else "disabled", text="Hentikan")
        has_outputs = "normal" if (self.outputs and not running) else "disabled"
        for button in (self.btn_pdf, self.btn_xlsx, self.btn_folder):
            button.configure(state=has_outputs)

    def _finish(self, status):
        self._set_running(False, status)
        self.app._update_global_ui_state()

    def _open(self, kind):
        if not self.outputs:
            return
        target = {"pdf": self.outputs.pdf, "xlsx": self.outputs.xlsx, "folder": self.outputs.pdf.parent}[kind]
        if not engine.open_in_file_manager(str(target)):
            messagebox.showinfo("Informasi", f"Berkas tidak ditemukan:\n{target}")

    # -------------------------------------------------------------- worker
    def _worker(self, source, output, use_ocr):
        from solcoat_research.pipeline import ScanStopped
        from solcoat_research.runner import run_research

        self._log("=" * 60)
        self._log(f"[INFO] Riset Solcoat: {engine.display_path(source)}")
        self._log("=" * 60)
        try:
            outputs = run_research(source, output, use_ocr=use_ocr, log=self._log, stop_event=self.stop_event)
        except ScanStopped:
            self._log("[STOP] Riset dihentikan. Hasil OCR yang sudah selesai tersimpan di cache.")
            self.ui_queue.put(lambda: self._finish("Riset dihentikan pengguna."))
        except Exception as exc:
            LOGGER.exception("Research run failed")
            self._log(f"[ERROR] Riset gagal: {exc}")
            message = f"Riset gagal: {exc}"
            self.ui_queue.put(lambda: self._finish(message))
        else:
            self.outputs = outputs
            ocr_note = "" if outputs.ocr_used else " (tanpa OCR)"
            summary = (f"Selesai{ocr_note}: {outputs.documents} dokumen, {outputs.pages:,} halaman "
                       f"({outputs.ocr_pages:,} OCR), {outputs.facts:,} fakta, {outputs.equipment_tier_a} alat tier A.")
            self._log(f"[SUKSES] {summary}")
            self._log(f"[SUKSES] Laporan PDF : {engine.display_path(str(outputs.pdf))}")
            self._log(f"[SUKSES] Data Excel  : {engine.display_path(str(outputs.xlsx))}")
            self.ui_queue.put(lambda: self._finish(summary))
