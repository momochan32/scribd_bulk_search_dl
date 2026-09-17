"""Tab 'Analisis Lanjutan' — terpisah dari tab 'Kesiapan Hitung Furnace'.

Memakai folder sumber dan folder hasil yang sama dengan tab Kesiapan Hitung Furnace. Tugas panjang (laporan per
perusahaan, impor dokumen klien) berjalan di thread; pembaruan UI diantrekan dan diterapkan di thread utama.
"""

import logging
import queue
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

import scribd_engine as engine
from research_panel import SOLCOAT_GREEN, SOLCOAT_GREEN_HOVER, format_duration

LOGGER = logging.getLogger("momo_rescribd")
TAB_NAME = "Analisis Lanjutan"
TOOLS = (
    ("Laporan per Perusahaan", "PDF + Excel terpisah per klien — data satu klien tidak masuk laporan klien lain."),
    ("Skor Prospek", "Urutan prospek industri (hasil riset) dan PLTU (SOF/EAF/EFOR PLN NP 2025)."),
    ("NPV Degradasi ε", "NPV, IRR, dan payback terdiskonto dengan emisivitas turun 0,98 → 0,80."),
    ("Akurasi Ekstraksi", "Presisi hasil ekstraksi per tingkat keyakinan & metode, dari verifikasi analis."),
    ("Impor Dokumen Klien", "Datasheet API 560 / refractory schedule klien → riset sumber primer terpisah."),
)


class AnalysisPanel:
    def __init__(self, app, tab, font_family):
        self.app, self.font = app, font_family
        self.log_queue, self.ui_queue = queue.Queue(), queue.Queue()
        self.thread, self.started_at, self.last_folder = None, None, None
        self._build(tab)

    def _build(self, tab):
        ctk.CTkLabel(tab, text="Analisis lanjutan untuk tim teknis & analis — memakai folder sumber dan hasil dari tab "
                               "'Kesiapan Hitung Furnace'.", font=(self.font, 11, "bold"), text_color="#cbd5e1").pack(
            anchor="w", pady=(2, 6))
        commands = (self.company_reports, self.open_prospects, self.open_npv, self.open_accuracy, self.import_client)
        for (title, description), command in zip(TOOLS, commands):
            row = ctk.CTkFrame(tab, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkButton(row, text=title, width=190, height=30, fg_color=SOLCOAT_GREEN, hover_color=SOLCOAT_GREEN_HOVER,
                          font=(self.font, 11, "bold"), command=command).pack(side="left")
            ctk.CTkLabel(row, text=description, font=(self.font, 10), text_color="#94a3b8").pack(side="left", padx=10)
        status = ctk.CTkFrame(tab, fg_color="transparent")
        status.pack(fill="x", pady=(6, 0))
        self.status = ctk.CTkLabel(status, text="Siap.", font=(self.font, 10), text_color="#64748b", anchor="w")
        self.status.pack(side="left")
        self.btn_folder = ctk.CTkButton(status, text="Buka Folder Hasil", width=130, height=26, state="disabled",
                                        fg_color="#334155", hover_color="#475569", command=self.open_last_folder)
        self.btn_folder.pack(side="right")

    # ------------------------------------------------------------------ helpers
    def _research(self):
        panel = self.app.research_panel
        output_dir, db_path = panel._research_db()
        return panel, Path(panel._source()), output_dir, db_path

    def is_running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def _log(self, message: str):
        elapsed = format_duration(time.monotonic() - self.started_at) if self.started_at else "00:00"
        self.log_queue.put(f"[{elapsed}] {message}\n")

    def poll(self):
        textbox = self.app.active_console_tabs.get(TAB_NAME)
        while textbox is not None and not self.log_queue.empty():
            textbox.insert("end", self.log_queue.get_nowait())
            textbox.see("end")
        if self.is_running() and self.started_at:
            self.status.configure(text=f"Berjalan {format_duration(time.monotonic() - self.started_at)}…")
        while not self.ui_queue.empty():
            self.ui_queue.get_nowait()()

    def _start(self, label: str, work):
        if self.is_running():
            messagebox.showinfo("Masih Berjalan", "Tunggu tugas analisis yang sedang berjalan selesai.")
            return
        self.app._ensure_solo_tab(TAB_NAME)
        self.started_at = time.monotonic()
        self.status.configure(text=f"{label} berjalan…")
        self._log(f"[INFO] {label} dimulai")

        def run():
            try:
                folder, summary = work()
            except Exception as exc:
                LOGGER.exception("%s failed", label)
                message = f"{label} gagal: {exc}"
                self._log(f"[ERROR] {message}")
                self.ui_queue.put(lambda: self.status.configure(text=message))
                return
            self._log(f"[SUKSES] {summary}")
            self.ui_queue.put(lambda: self._finish(folder, summary))

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def _finish(self, folder: Path, summary: str):
        self.last_folder = folder
        self.btn_folder.configure(state="normal")
        self.status.configure(text=f"{summary} · {format_duration(time.monotonic() - self.started_at)}")

    def open_last_folder(self):
        if self.last_folder:
            engine.open_in_file_manager(str(self.last_folder))

    # ------------------------------------------------------------------ tools
    def company_reports(self):
        panel, source, output_dir, _ = self._research()
        if not source.is_dir():
            messagebox.showwarning("Peringatan", f"Folder PDF sumber tidak ditemukan:\n{source}")
            return

        use_ocr = panel.ocr_var.get()  # Tk variables must be read on the main thread

        def work():
            from solcoat_research.company_reports import COMPANY_FOLDER, run_company_reports
            reports = run_company_reports(source, output_dir, use_ocr=use_ocr, log=self._log)
            return output_dir / COMPANY_FOLDER, f"{len(reports)} laporan per perusahaan dibuat"

        self._start("Laporan per perusahaan", work)

    def import_client(self):
        folder = filedialog.askdirectory(parent=self.app, title="Pilih folder dokumen klien (datasheet, refractory schedule)")
        if not folder:
            return
        use_ocr = self.app.research_panel.ocr_var.get()  # Tk variables must be read on the main thread

        def work():
            from solcoat_research.runner import run_research
            outputs = run_research(Path(folder), use_ocr=use_ocr, log=self._log, client_documents=True)
            return outputs.pdf.parent, (f"Dokumen klien: {outputs.documents} dokumen, {outputs.facts} fakta "
                                        f"(sumber primer) -> {outputs.pdf.name}")

        self._start("Impor dokumen klien", work)

    def open_prospects(self):
        from analysis_dialogs import ProspectDialog
        _, _, output_dir, db_path = self._research()
        return ProspectDialog(self.app, db_path if db_path.exists() else None, output_dir, self.font)

    def open_accuracy(self):
        from analysis_dialogs import AccuracyDialog
        _, _, _, db_path = self._research()
        return AccuracyDialog(self.app, db_path if db_path.exists() else None, self.font)

    def open_npv(self):
        from analysis_dialogs import NpvDialog
        _, _, output_dir, _ = self._research()
        return NpvDialog(self.app, output_dir, self.font)
