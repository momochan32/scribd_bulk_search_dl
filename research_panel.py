"""Tab "Riset Solcoat" untuk Momo Rescribd.

Membaca PDF hasil unduhan (text layer + OCR), menautkan angka ke peralatan, lalu menyusun laporan PDF
dan Excel untuk tim teknis & analis Solcoat. Riset boleh berjalan bersamaan dengan unduhan. Logika riset
ada di research/solcoat_research; modul ini hanya UI dan thread pekerja.
"""

import logging
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

import scribd_engine as engine

_RESEARCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "research")
if os.path.isdir(_RESEARCH_DIR) and _RESEARCH_DIR not in sys.path:
    sys.path.insert(0, _RESEARCH_DIR)

LOGGER = logging.getLogger("momo_rescribd")

TAB_NAME = "Kesiapan Hitung Furnace"
SOLCOAT_GREEN = "#338B34"
SOLCOAT_GREEN_HOVER = "#1F5A20"
MIN_FRACTION_FOR_ETA = 0.03
MIN_SECONDS_FOR_ETA = 10  # tahap awal (hash/cache) terlalu cepat untuk dijadikan dasar tebakan
MISSING_DEPS_MESSAGE = (
    "Fitur Riset Solcoat membutuhkan paket tambahan (pymupdf, reportlab, openpyxl, pyyaml).\n\n"
    "Jalankan: pip install -r requirements.txt"
)


def format_duration(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def estimate_remaining(elapsed: float, fraction: float) -> float | None:
    """Sisa waktu linear terhadap progres keseluruhan; None bila progres masih terlalu kecil untuk ditebak."""
    if fraction < MIN_FRACTION_FOR_ETA or fraction >= 1 or elapsed < MIN_SECONDS_FOR_ETA:
        return None
    return elapsed * (1 - fraction) / fraction


def download_friendly_workers(downloads_running: bool) -> int | None:
    """Saat Chrome sedang mengunduh, OCR memakai separuh inti CPU agar unduhan tetap lancar."""
    return max(1, (os.cpu_count() or 2) // 2) if downloads_running else None


class ResearchPanel:
    def __init__(self, app, tab, font_family):
        self.app = app
        self.font = font_family
        self.source_var = tk.StringVar(value=app.base_folder_var.get())
        self.output_var = tk.StringVar(value="")
        self.ocr_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Pilih folder berisi PDF hasil unduhan, lalu klik Mulai Riset.")
        self.progress_text_var = tk.StringVar(value="")
        self.log_queue = queue.Queue()
        # Tk is not thread-safe: the worker never touches widgets. It queues UI callables and writes the latest
        # progress snapshot under a lock; poll() applies both on the main thread.
        self.ui_queue = queue.Queue()
        self._progress_lock = threading.Lock()
        self._progress = ("", 0.0, "")
        self.stop_event = threading.Event()
        self.thread = None
        self.outputs = None
        self.started_at = None
        self._build(tab)

    # ------------------------------------------------------------------ UI
    def _folder_row(self, tab, label, variable, placeholder):
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", pady=(0, 6))
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
            tab, text="Riset sumber PDF untuk tim teknis & analis Solcoat (tanpa AI) — bisa berjalan sambil mengunduh:",
            font=(self.font, 11, "bold"), text_color="#cbd5e1",
        ).pack(anchor="w", pady=(2, 4))
        self._folder_row(tab, "Folder PDF sumber:", self.source_var, "Folder hasil unduhan, mis. Downloads/Momo_Rescribd")
        self._folder_row(tab, "Folder laporan:", self.output_var, "Kosongkan: otomatis <folder sumber>_Riset_Solcoat")

        ctk.CTkCheckBox(
            tab, text="Baca halaman scan dengan OCR (data bahasa ±5 MB diunduh otomatis saat pertama)",
            variable=self.ocr_var, font=(self.font, 11), fg_color=SOLCOAT_GREEN, hover_color=SOLCOAT_GREEN_HOVER,
        ).pack(anchor="w", pady=(0, 6))

        actions = ctk.CTkFrame(tab, fg_color="transparent")
        actions.pack(fill="x", pady=(0, 6))
        self.btn_start = self._button(actions, "Mulai Riset", self.start, width=120, primary=True)
        self.btn_start.pack(side="left", padx=(0, 6))
        self.btn_stop = self._button(actions, "Hentikan", self.stop, width=84, state="disabled")
        self.btn_stop.pack(side="left", padx=(0, 12))
        self.btn_pdf = self._button(actions, "Buka Laporan PDF", lambda: self._open("pdf"), width=128, state="disabled")
        self.btn_pdf.pack(side="left", padx=(0, 6))
        self.btn_xlsx = self._button(actions, "Buka Excel", lambda: self._open("xlsx"), width=90, state="disabled")
        self.btn_xlsx.pack(side="left", padx=(0, 6))
        self.btn_folder = self._button(actions, "Buka Folder", lambda: self._open("folder"), width=96, state="disabled")
        self.btn_folder.pack(side="left")

        tools = ctk.CTkFrame(tab, fg_color="transparent")
        tools.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(tools, text="Alat analis:", font=(self.font, 11, "bold"), text_color="#cbd5e1", width=120,
                     anchor="w").pack(side="left")
        self.btn_verify = self._button(tools, "Verifikasi Fakta", self.open_verifier, width=130, primary=True)
        self.btn_verify.pack(side="left", padx=(0, 6))
        self.btn_calc = self._button(tools, "Hitung dengan Asumsi", self.open_calculator, width=160, primary=True)
        self.btn_calc.pack(side="left", padx=(0, 6))
        self.btn_pltu = self._button(tools, "Mode PLTU", self.open_pltu, width=110, primary=True)
        self.btn_pltu.pack(side="left")

        progress_row = ctk.CTkFrame(tab, fg_color="transparent")
        progress_row.pack(fill="x", pady=(0, 2))
        self.progress_bar = ctk.CTkProgressBar(progress_row, height=10, progress_color=SOLCOAT_GREEN)
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.progress_bar.set(0)
        ctk.CTkLabel(progress_row, textvariable=self.progress_text_var, font=(self.font, 10), text_color="#cbd5e1",
                     width=430, anchor="w").pack(side="right")

        ctk.CTkLabel(tab, textvariable=self.status_var, font=(self.font, 10), text_color="#64748b",
                     anchor="w", justify="left").pack(anchor="w")

    def _browse(self, variable):
        self.app.update_idletasks()
        initial = variable.get().strip() or self.source_var.get().strip() or self.app.base_folder_var.get()
        chosen = filedialog.askdirectory(parent=self.app, title="Pilih Folder", initialdir=os.path.expanduser(initial))
        if chosen:
            variable.set(chosen)

    # ------------------------------------------------------------ helpers
    def _source(self) -> str:
        return os.path.expanduser(self.source_var.get().strip())

    def _output_dir(self) -> Path | None:
        custom = self.output_var.get().strip()
        if custom:
            return Path(os.path.expanduser(custom))
        if self.outputs:
            return self.outputs.pdf.parent
        source = self._source()
        if not source:
            return None
        from solcoat_research.runner import default_output_dir
        return default_output_dir(Path(source))

    def _elapsed(self) -> float:
        return time.monotonic() - self.started_at if self.started_at else 0.0

    # ------------------------------------------------------------ actions
    def is_running(self):
        return bool(self.thread and self.thread.is_alive())

    def start(self):
        if self.is_running():
            return
        source = self._source()
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
        self.started_at = time.monotonic()
        self._set_progress("Menyiapkan", 0.0, "")
        self._set_running(True, "Riset berjalan… log lengkap tampil di konsol tab 'Riset Solcoat'.")
        workers = download_friendly_workers(self.app._any_download_running())
        output = os.path.expanduser(self.output_var.get().strip()) or None
        self.thread = threading.Thread(target=self._worker, args=(source, output, self.ocr_var.get(), workers),
                                       daemon=True)
        self.thread.start()
        self.app._update_global_ui_state()

    def stop(self):
        if self.is_running():
            self.stop_event.set()
            self._log("[STOP] Menghentikan riset setelah langkah yang sedang berjalan…")
            self.btn_stop.configure(state="disabled", text="Menghentikan")

    def _research_db(self) -> tuple[Path, Path]:
        output_dir = self._output_dir() or Path(self.app._get_base_folder())
        return output_dir, (self.outputs.db if self.outputs else output_dir / "research.db")

    def _import_dialog(self, module: str, name: str):
        try:
            return getattr(__import__(module), name)
        except ImportError as exc:
            LOGGER.error("Dialog %s dependencies missing: %s", module, exc)
            messagebox.showerror("Paket Belum Terpasang", f"{MISSING_DEPS_MESSAGE}\n\nDetail: {exc}")
            return None

    def open_calculator(self):
        dialog = self._import_dialog("calc_dialog", "CalcAssumptionDialog")
        if dialog is None:
            return None
        output_dir, db_path = self._research_db()
        if self.is_running():
            messagebox.showinfo("Riset Masih Berjalan", "Kalkulator memakai hasil riset terakhir yang sudah selesai.")
        return dialog(self.app, db_path if db_path.exists() else None, output_dir, self.font)

    def open_verifier(self):
        dialog = self._import_dialog("verify_dialog", "VerifyDialog")
        if dialog is None:
            return None
        _, db_path = self._research_db()
        if not db_path.exists():
            messagebox.showinfo("Belum Ada Hasil Riset", "Jalankan 'Mulai Riset' dulu untuk folder sumber ini.")
            return None
        return dialog(self.app, db_path, self.font)

    def open_pltu(self):
        dialog = self._import_dialog("pltu_dialog", "PltuDialog")
        if dialog is None:
            return None
        output_dir, _ = self._research_db()
        return dialog(self.app, output_dir, self.font)

    def poll(self):
        """Dipanggil loop polling GUI (thread utama): log, progres + timer, dan pembaruan UI dari pekerja."""
        textbox = self.app.active_console_tabs.get(TAB_NAME)
        if textbox is not None and not self.log_queue.empty():
            while not self.log_queue.empty():
                try:
                    textbox.insert("end", self.log_queue.get_nowait())
                except queue.Empty:
                    break
            textbox.see("end")
        if self.is_running():
            self._render_progress()
        while not self.ui_queue.empty():
            try:
                self.ui_queue.get_nowait()()
            except queue.Empty:
                break

    def _set_progress(self, label: str, fraction: float, detail: str):
        with self._progress_lock:
            self._progress = (label, fraction, detail)

    def _render_progress(self):
        with self._progress_lock:
            label, fraction, detail = self._progress
        elapsed = self._elapsed()
        remaining = estimate_remaining(elapsed, fraction)
        eta = f"sisa ±{format_duration(remaining)}" if remaining is not None else "sisa: menghitung…"
        parts = [label, detail, f"{fraction * 100:.0f}%", f"berjalan {format_duration(elapsed)}", eta]
        self.progress_bar.set(fraction)
        self.progress_text_var.set("  ·  ".join(p for p in parts if p))

    def _log(self, message):
        self.log_queue.put(f"[{format_duration(self._elapsed())}] {message}\n")

    def _set_running(self, running, status):
        self.status_var.set(status)
        self.btn_start.configure(state="disabled" if running else "normal",
                                 fg_color="#475569" if running else SOLCOAT_GREEN)
        self.btn_stop.configure(state="normal" if running else "disabled", text="Hentikan")
        has_outputs = "normal" if (self.outputs and not running) else "disabled"
        for button in (self.btn_pdf, self.btn_xlsx, self.btn_folder):
            button.configure(state=has_outputs)

    def _finish(self, status, fraction=None):
        elapsed = format_duration(self._elapsed())
        if fraction is not None:
            self.progress_bar.set(fraction)
        with self._progress_lock:
            label = self._progress[0]
        self.progress_text_var.set(f"Selesai dalam {elapsed}" if fraction == 1.0
                                   else f"{label} · berhenti pada {elapsed}")
        self._set_running(False, status)
        self.app._update_global_ui_state()

    def _open(self, kind):
        if not self.outputs:
            return
        target = {"pdf": self.outputs.pdf, "xlsx": self.outputs.xlsx, "folder": self.outputs.pdf.parent}[kind]
        if not engine.open_in_file_manager(str(target)):
            messagebox.showinfo("Informasi", f"Berkas tidak ditemukan:\n{target}")

    # -------------------------------------------------------------- worker
    def _worker(self, source, output, use_ocr, workers):
        from solcoat_research.pipeline import ScanStopped
        from solcoat_research.runner import run_research

        self._log("=" * 56)
        self._log(f"[INFO] Riset Solcoat: {engine.display_path(source)}")
        if workers:
            self._log(f"[INFO] Unduhan sedang berjalan: OCR memakai {workers} proses agar unduhan tetap lancar. "
                      "PDF yang selesai diunduh setelah ini ikut di riset berikutnya (cache membuatnya cepat).")
        self._log("=" * 56)
        try:
            outputs = run_research(source, output, use_ocr=use_ocr, workers=workers, log=self._log,
                                   stop_event=self.stop_event, progress=self._set_progress)
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
            self._log(f"[SUKSES] {summary} Waktu total {format_duration(self._elapsed())}.")
            self._log(f"[SUKSES] Laporan PDF : {engine.display_path(str(outputs.pdf))}")
            self._log(f"[SUKSES] Data Excel  : {engine.display_path(str(outputs.xlsx))}")
            self.ui_queue.put(lambda: self._finish(summary, fraction=1.0))
