#!/usr/bin/env python3
"""
Momo Rescribd — Modern Desktop Interface for Scribd Bulk Search & Downloader.
Built with CustomTkinter for native dark-mode styling, high contrast, and cross-platform reliability.
Supports macOS, Windows, and Linux.
"""

import os
import queue
import random
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

import scribd_engine as engine


# ---------------------------------------------------------------------------
# Cross-Platform Configurations
# ---------------------------------------------------------------------------
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

FONT_FAMILY_MAIN = "Segoe UI" if IS_WINDOWS else ("SF Pro Display" if IS_MAC else "Ubuntu")
FONT_FAMILY_MONO = "Consolas" if IS_WINDOWS else ("Menlo" if IS_MAC else "Monospace")

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ---------------------------------------------------------------------------
# Queue Writer for Thread-Safe Console Redirection
# ---------------------------------------------------------------------------
class QueueWriter:
    """Redirects stdout/stderr writes to a thread-safe Queue for UI rendering."""

    def __init__(self, log_queue):
        self.queue = log_queue

    def write(self, text):
        if text:
            self.queue.put(text)

    def flush(self):
        pass


# ---------------------------------------------------------------------------
# Main Application Window
# ---------------------------------------------------------------------------
class MomoRescribdApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Momo Rescribd — Scribd Bulk Search & Downloader")
        self.geometry("920x820")
        self.minsize(780, 700)

        # Set App Icon
        self._set_app_icon()

        # State Variables
        self.is_running = False
        self.worker_thread = None
        self.stop_event = threading.Event()
        self.log_queue = queue.Queue()

        self.output_dir_var = tk.StringVar(value="")
        self.single_url_var = tk.StringVar(value="")
        self.file_path_var = tk.StringVar(value="")
        self.limit_var = tk.StringVar(value="5")
        self.min_delay_var = tk.StringVar(value="1.0")
        self.max_delay_var = tk.StringVar(value="5.0")

        self._build_ui()
        self._poll_log_queue()

    def _set_app_icon(self):
        """Set window icon for Windows and macOS."""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        ico_path = os.path.join(base_dir, "assets", "momo_rescribd.ico")
        if IS_WINDOWS and os.path.exists(ico_path):
            try:
                self.iconbitmap(ico_path)
            except Exception:
                pass

    # ---------------------------------------------------------------------------
    # UI Component Construction
    # ---------------------------------------------------------------------------
    def _build_ui(self):
        # Root layout container
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=22, pady=18)

        # 1. Header Area with Mascot Logo
        self._build_header(self.main_container)

        # 2. Main Tabview (Modes)
        self._build_tabs(self.main_container)

        # 3. Settings Card (Random Delay & Folder)
        self._build_settings_card(self.main_container)

        # 4. Action Bar (Start, Stop, Open Folder, Progress Bar)
        self._build_action_bar(self.main_container)

        # 5. Activity Log Console
        self._build_console_card(self.main_container)

    def _build_header(self, parent):
        header_frame = ctk.CTkFrame(parent, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 14))

        # Left: Logo + App Titles
        left_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        left_box.pack(side="left", fill="y")

        # Load Mascot Logo
        base_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(base_dir, "assets", "logo.png")
        if os.path.exists(logo_path):
            try:
                pil_logo = Image.open(logo_path)
                self.logo_image = ctk.CTkImage(light_image=pil_logo, dark_image=pil_logo, size=(58, 58))
                logo_label = ctk.CTkLabel(left_box, image=self.logo_image, text="")
                logo_label.pack(side="left", padx=(0, 14))
            except Exception:
                pass

        titles_box = ctk.CTkFrame(left_box, fg_color="transparent")
        titles_box.pack(side="left", fill="y")

        app_title = ctk.CTkLabel(
            titles_box,
            text="Momo Rescribd",
            font=(FONT_FAMILY_MAIN, 22, "bold"),
            text_color="#f8fafc",
        )
        app_title.pack(anchor="w")

        app_subtitle = ctk.CTkLabel(
            titles_box,
            text="Scribd Bulk Search & Document Downloader",
            font=(FONT_FAMILY_MAIN, 12),
            text_color="#94a3b8",
        )
        app_subtitle.pack(anchor="w", pady=(2, 0))

        # Right: Status Indicator Badge
        right_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        right_box.pack(side="right", fill="y")

        self.status_badge = ctk.CTkLabel(
            right_box,
            text="SIAP",
            font=(FONT_FAMILY_MAIN, 11, "bold"),
            text_color="#10b981",
            fg_color="#064e3b",
            corner_radius=8,
            padx=16,
            pady=6,
        )
        self.status_badge.pack(anchor="e", pady=(4, 0))

    def _build_tabs(self, parent):
        self.tabview = ctk.CTkTabview(parent, height=180, corner_radius=10)
        self.tabview.pack(fill="x", pady=(0, 12))

        # Tab 1: Multi-Keyword Search
        self.tab_search = self.tabview.add("Pencarian Kata Kunci")
        self._build_search_tab(self.tab_search)

        # Tab 2: Single URL
        self.tab_single = self.tabview.add("Tautan Tunggal")
        self._build_single_tab(self.tab_single)

        # Tab 3: Batch URL File
        self.tab_file = self.tabview.add("Berkas Daftar URL")
        self._build_file_tab(self.tab_file)

    def _build_search_tab(self, tab):
        lbl = ctk.CTkLabel(
            tab,
            text="Daftar Kata Kunci (masukkan satu kata kunci per baris atau pisahkan dengan tanda koma):",
            font=(FONT_FAMILY_MAIN, 11),
            text_color="#cbd5e1",
        )
        lbl.pack(anchor="w", pady=(0, 6))

        self.keywords_textbox = ctk.CTkTextbox(tab, height=72, font=(FONT_FAMILY_MAIN, 12), corner_radius=8)
        self.keywords_textbox.pack(fill="x", pady=(0, 8))
        self.keywords_textbox.insert("1.0", "Petrokimia Gresik\nPupuk Kaltim\nPupuk Indonesia")
        self.keywords_textbox.bind("<KeyRelease>", self._update_keyword_count)

        # Bottom row inside Tab 1
        sub_row = ctk.CTkFrame(tab, fg_color="transparent")
        sub_row.pack(fill="x")

        self.kw_counter_label = ctk.CTkLabel(
            sub_row,
            text="3 kata kunci terdeteksi",
            font=(FONT_FAMILY_MAIN, 11, "bold"),
            text_color="#60a5fa",
        )
        self.kw_counter_label.pack(side="left")

        btn_sample = ctk.CTkButton(
            sub_row,
            text="Reset Contoh",
            width=90,
            height=26,
            font=(FONT_FAMILY_MAIN, 10),
            fg_color="#334155",
            hover_color="#475569",
            command=self._reset_sample_keywords,
        )
        btn_sample.pack(side="left", padx=(12, 0))

        # Target documents per keyword
        limit_box = ctk.CTkFrame(sub_row, fg_color="transparent")
        limit_box.pack(side="right")

        ctk.CTkLabel(
            limit_box,
            text="Target Dokumen per Kata Kunci:",
            font=(FONT_FAMILY_MAIN, 11),
            text_color="#cbd5e1",
        ).pack(side="left", padx=(0, 8))

        self.entry_limit = ctk.CTkEntry(
            limit_box,
            textvariable=self.limit_var,
            width=55,
            height=28,
            font=(FONT_FAMILY_MAIN, 12),
            justify="center",
        )
        self.entry_limit.pack(side="left")

    def _build_single_tab(self, tab):
        lbl = ctk.CTkLabel(
            tab,
            text="Tautan Dokumen Scribd Spesifik:",
            font=(FONT_FAMILY_MAIN, 11),
            text_color="#cbd5e1",
        )
        lbl.pack(anchor="w", pady=(0, 8))

        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", pady=(0, 8))

        self.entry_single_url = ctk.CTkEntry(
            row,
            textvariable=self.single_url_var,
            placeholder_text="https://www.scribd.com/document/123456789/Judul-Dokumen",
            font=(FONT_FAMILY_MAIN, 12),
            height=34,
        )
        self.entry_single_url.pack(side="left", fill="x", expand=True, padx=(0, 10))

        btn_paste = ctk.CTkButton(
            row,
            text="Tempel Tautan",
            width=110,
            height=34,
            font=(FONT_FAMILY_MAIN, 11),
            fg_color="#334155",
            hover_color="#475569",
            command=self._paste_single_url,
        )
        btn_paste.pack(side="right")

        hint = ctk.CTkLabel(
            tab,
            text="Sistem akan langsung membuka peramban latar belakang dan mengonversi seluruh halaman dokumen ke format PDF asli.",
            font=(FONT_FAMILY_MAIN, 10),
            text_color="#64748b",
        )
        hint.pack(anchor="w")

    def _build_file_tab(self, tab):
        lbl = ctk.CTkLabel(
            tab,
            text="Lokasi Berkas Teks Daftar URL (format satu link per baris):",
            font=(FONT_FAMILY_MAIN, 11),
            text_color="#cbd5e1",
        )
        lbl.pack(anchor="w", pady=(0, 8))

        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", pady=(0, 8))

        self.entry_file_path = ctk.CTkEntry(
            row,
            textvariable=self.file_path_var,
            placeholder_text="Pilih berkas urls.txt...",
            font=(FONT_FAMILY_MAIN, 12),
            height=34,
        )
        self.entry_file_path.pack(side="left", fill="x", expand=True, padx=(0, 10))

        btn_browse = ctk.CTkButton(
            row,
            text="Pilih Berkas...",
            width=110,
            height=34,
            font=(FONT_FAMILY_MAIN, 11),
            fg_color="#334155",
            hover_color="#475569",
            command=self._browse_file,
        )
        btn_browse.pack(side="right")

    def _build_settings_card(self, parent):
        card = ctk.CTkFrame(parent, corner_radius=10, fg_color="#1e293b", border_width=1, border_color="#334155")
        card.pack(fill="x", pady=(0, 12), padx=2, ipady=4)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=12)

        # Row 1: Random Delay Range
        row1 = ctk.CTkFrame(inner, fg_color="transparent")
        row1.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            row1,
            text="Rentang Jeda Acak (detik):",
            font=(FONT_FAMILY_MAIN, 11, "bold"),
            text_color="#f8fafc",
        ).pack(side="left", padx=(0, 10))

        self.entry_min_delay = ctk.CTkEntry(
            row1,
            textvariable=self.min_delay_var,
            width=48,
            height=28,
            justify="center",
            font=(FONT_FAMILY_MAIN, 11),
        )
        self.entry_min_delay.pack(side="left")

        ctk.CTkLabel(row1, text="s/d", font=(FONT_FAMILY_MAIN, 11), text_color="#94a3b8").pack(side="left", padx=8)

        self.entry_max_delay = ctk.CTkEntry(
            row1,
            textvariable=self.max_delay_var,
            width=48,
            height=28,
            justify="center",
            font=(FONT_FAMILY_MAIN, 11),
        )
        self.entry_max_delay.pack(side="left")

        ctk.CTkLabel(row1, text="detik", font=(FONT_FAMILY_MAIN, 11), text_color="#94a3b8").pack(side="left", padx=(8, 14))

        ctk.CTkLabel(
            row1,
            text="Jeda diacak otomatis antara 1000 - 5000 ms antar dokumen untuk mencegah rate-limit",
            font=(FONT_FAMILY_MAIN, 10),
            text_color="#64748b",
        ).pack(side="left")

        # Row 2: Destination Folder
        row2 = ctk.CTkFrame(inner, fg_color="transparent")
        row2.pack(fill="x")

        ctk.CTkLabel(
            row2,
            text="Direktori Simpan PDF:",
            font=(FONT_FAMILY_MAIN, 11, "bold"),
            text_color="#f8fafc",
        ).pack(side="left", padx=(0, 10))

        self.entry_folder = ctk.CTkEntry(
            row2,
            textvariable=self.output_dir_var,
            placeholder_text="Kosongkan untuk otomatis menyimpan ke folder Downloads/Momo_Rescribd",
            font=(FONT_FAMILY_MAIN, 11),
            height=30,
        )
        self.entry_folder.pack(side="left", fill="x", expand=True, padx=(0, 10))

        btn_folder = ctk.CTkButton(
            row2,
            text="Pilih Folder...",
            width=110,
            height=30,
            font=(FONT_FAMILY_MAIN, 11),
            fg_color="#334155",
            hover_color="#475569",
            command=self._browse_folder,
        )
        btn_folder.pack(side="right")

    def _build_action_bar(self, parent):
        action_row = ctk.CTkFrame(parent, fg_color="transparent")
        action_row.pack(fill="x", pady=(0, 12))

        # Start Button
        self.btn_start = ctk.CTkButton(
            action_row,
            text="Mulai Unduh",
            font=(FONT_FAMILY_MAIN, 12, "bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            height=38,
            width=150,
            corner_radius=8,
            command=self._start_process,
        )
        self.btn_start.pack(side="left", padx=(0, 10))

        # Stop Button
        self.btn_stop = ctk.CTkButton(
            action_row,
            text="Hentikan Proses",
            font=(FONT_FAMILY_MAIN, 12, "bold"),
            fg_color="#dc2626",
            hover_color="#b91c1c",
            height=38,
            width=140,
            corner_radius=8,
            state="disabled",
            command=self._stop_process,
        )
        self.btn_stop.pack(side="left", padx=(0, 12))

        # Open Output Folder Button
        self.btn_open_folder = ctk.CTkButton(
            action_row,
            text="Buka Folder Hasil",
            font=(FONT_FAMILY_MAIN, 11),
            fg_color="#1e293b",
            hover_color="#334155",
            border_width=1,
            border_color="#475569",
            height=38,
            width=140,
            corner_radius=8,
            command=self._open_output_folder,
        )
        self.btn_open_folder.pack(side="left")

        # Progress Bar
        self.progress_bar = ctk.CTkProgressBar(
            action_row,
            orientation="horizontal",
            mode="indeterminate",
            height=10,
            width=180,
            corner_radius=5,
            progress_color="#3b82f6",
        )
        self.progress_bar.pack(side="right", padx=(10, 0))
        self.progress_bar.set(0)

    def _build_console_card(self, parent):
        console_frame = ctk.CTkFrame(
            parent,
            corner_radius=10,
            fg_color="#0b0f19",
            border_width=1,
            border_color="#1e293b",
        )
        console_frame.pack(fill="both", expand=True)

        # Header Bar
        top_bar = ctk.CTkFrame(console_frame, height=34, fg_color="#111827", corner_radius=0)
        top_bar.pack(fill="x", padx=1, pady=1)

        ctk.CTkLabel(
            top_bar,
            text="Log Aktivitas & Status Konsol",
            font=(FONT_FAMILY_MAIN, 11, "bold"),
            text_color="#94a3b8",
        ).pack(side="left", padx=12, pady=4)

        btn_copy = ctk.CTkButton(
            top_bar,
            text="Salin Log",
            width=70,
            height=24,
            font=(FONT_FAMILY_MAIN, 10),
            fg_color="#1f2937",
            hover_color="#374151",
            command=self._copy_log,
        )
        btn_copy.pack(side="right", padx=(6, 8), pady=4)

        btn_clear = ctk.CTkButton(
            top_bar,
            text="Bersihkan",
            width=70,
            height=24,
            font=(FONT_FAMILY_MAIN, 10),
            fg_color="#1f2937",
            hover_color="#374151",
            command=self._clear_log,
        )
        btn_clear.pack(side="right", pady=4)

        # Text Console Output
        self.log_textbox = ctk.CTkTextbox(
            console_frame,
            font=(FONT_FAMILY_MONO, 11),
            text_color="#e2e8f0",
            fg_color="#0b0f19",
            wrap="word",
            corner_radius=8,
        )
        self.log_textbox.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        # Welcome message
        self.log_textbox.insert(
            "end",
            "Momo Rescribd siap digunakan.\n"
            "Pilih mode pengunduhan di atas lalu klik 'Mulai Unduh'.\n\n"
        )

    # ---------------------------------------------------------------------------
    # Event Handlers & Helpers
    # ---------------------------------------------------------------------------
    def _update_keyword_count(self, event=None):
        raw = self.keywords_textbox.get("1.0", "end").strip()
        keywords = self._parse_keywords(raw)
        count = len(keywords)
        if count == 0:
            self.kw_counter_label.configure(text="Belum ada kata kunci", text_color="#ef4444")
        elif count == 1:
            self.kw_counter_label.configure(text="1 kata kunci terdeteksi", text_color="#60a5fa")
        else:
            self.kw_counter_label.configure(text=f"{count} kata kunci terdeteksi", text_color="#60a5fa")

    def _parse_keywords(self, raw_text):
        if not raw_text:
            return []
        tokens = raw_text.replace("\n", ",").split(",")
        return [t.strip() for t in tokens if t.strip()]

    def _reset_sample_keywords(self):
        self.keywords_textbox.delete("1.0", "end")
        self.keywords_textbox.insert("1.0", "Petrokimia Gresik\nPupuk Kaltim\nPupuk Indonesia")
        self._update_keyword_count()

    def _paste_single_url(self):
        try:
            clipboard = self.clipboard_get()
            self.single_url_var.set(clipboard.strip())
        except Exception:
            pass

    def _browse_file(self):
        f = filedialog.askopenfilename(
            title="Pilih Berkas Teks Daftar URL",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
        )
        if f:
            self.file_path_var.set(f)

    def _browse_folder(self):
        cur = self.output_dir_var.get().strip() or os.path.expanduser("~/Downloads")
        d = filedialog.askdirectory(title="Pilih Folder Simpan PDF", initialdir=cur)
        if d:
            self.output_dir_var.set(d)

    def _get_effective_output_dir(self):
        val = self.output_dir_var.get().strip()
        if val:
            path = os.path.expanduser(val)
        else:
            path = os.path.expanduser("~/Downloads/Momo_Rescribd")
        os.makedirs(path, exist_ok=True)
        return path

    def _open_output_folder(self):
        folder = self._get_effective_output_dir()
        if not engine.open_in_file_manager(folder):
            messagebox.showinfo("Informasi", f"Folder belum ada atau gagal dibuka:\n{engine.display_path(folder)}")

    def _clear_log(self):
        self.log_textbox.delete("1.0", "end")

    def _copy_log(self):
        text = self.log_textbox.get("1.0", "end")
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("Sukses", "Seluruh log berhasil disalin ke clipboard.")

    def _poll_log_queue(self):
        while not self.log_queue.empty():
            try:
                msg = self.log_queue.get_nowait()
                self.log_textbox.insert("end", msg)
                self.log_textbox.see("end")
            except queue.Empty:
                break
        self.after(50, self._poll_log_queue)

    def _log(self, text):
        self.log_queue.put(text + "\n")

    def _set_ui_state(self, running, status_text="SIAP", badge_type="ready"):
        self.is_running = running

        if running:
            self.btn_start.configure(state="disabled", fg_color="#475569")
            self.btn_stop.configure(state="normal", fg_color="#dc2626")
            self.progress_bar.start()
        else:
            self.btn_start.configure(state="normal", fg_color="#2563eb")
            self.btn_stop.configure(state="disabled", fg_color="#475569")
            self.progress_bar.stop()
            self.progress_bar.set(0)

        badge_configs = {
            "ready": ("#10b981", "#064e3b"),       # Green text, dark green bg
            "running": ("#f59e0b", "#78350f"),     # Amber text, dark amber bg
            "stopped": ("#ef4444", "#7f1d1d"),     # Red text, dark red bg
            "success": ("#38bdf8", "#0c4a6e"),     # Blue text, dark blue bg
        }
        fg_col, bg_col = badge_configs.get(badge_type, ("#10b981", "#064e3b"))
        self.status_badge.configure(text=status_text, text_color=fg_col, fg_color=bg_col)

    # ---------------------------------------------------------------------------
    # Start and Stop Process Handlers
    # ---------------------------------------------------------------------------
    def _stop_process(self):
        if not self.is_running:
            return

        self._log("\n[STOP] Mengirim sinyal berhenti... Menutup peramban dan membersihkan proses...")
        self.stop_event.set()
        self.btn_stop.configure(state="disabled", text="MENGHENTIKAN...")
        self.status_badge.configure(text="MENGHENTIKAN...", text_color="#ef4444", fg_color="#7f1d1d")

    def _start_process(self):
        if self.is_running:
            return

        active_tab_name = self.tabview.get()
        out_dir = self._get_effective_output_dir()

        # Parse Delays
        try:
            min_delay = max(0.5, float(self.min_delay_var.get().strip()))
            max_delay = max(min_delay, float(self.max_delay_var.get().strip()))
        except Exception:
            min_delay = 1.0
            max_delay = 5.0
            self.min_delay_var.set("1.0")
            self.max_delay_var.set("5.0")

        self.stop_event.clear()

        # Mode 1: Multi-Keyword Search
        if active_tab_name == "Pencarian Kata Kunci":
            raw_kw = self.keywords_textbox.get("1.0", "end").strip()
            keywords = self._parse_keywords(raw_kw)
            if not keywords:
                messagebox.showwarning("Peringatan", "Silakan masukkan minimal satu kata kunci pencarian.")
                return

            try:
                limit = max(1, int(self.limit_var.get().strip()))
            except Exception:
                limit = 5
                self.limit_var.set("5")

            self._set_ui_state(True, status_text="MEMPROSES", badge_type="running")
            self.btn_stop.configure(text="Hentikan Proses")

            self._log("=" * 60)
            self._log(f"[INFO] Memulai proses pencarian {len(keywords)} kata kunci.")
            self._log(f"[INFO] Target: {limit} dokumen per kata kunci.")
            self._log(f"[INFO] Jeda acak: {min_delay:.1f}s - {max_delay:.1f}s ({int(min_delay*1000)} - {int(max_delay*1000)} ms).")
            self._log(f"[INFO] Direktori simpan: {engine.display_path(out_dir)}")
            self._log("=" * 60)

            self.worker_thread = threading.Thread(
                target=self._run_multi_search_worker,
                args=(keywords, limit, out_dir, min_delay, max_delay),
                daemon=True,
            )
            self.worker_thread.start()

        # Mode 2: Single URL
        elif active_tab_name == "Tautan Tunggal":
            url = self.single_url_var.get().strip()
            if not url:
                messagebox.showwarning("Peringatan", "Silakan masukkan tautan dokumen Scribd.")
                return

            self._set_ui_state(True, status_text="MENGUNDUH", badge_type="running")
            self.btn_stop.configure(text="Hentikan Proses")

            self._log("=" * 60)
            self._log(f"[INFO] Mengunduh dokumen dari URL: {url}")
            self._log(f"[INFO] Direktori simpan: {engine.display_path(out_dir)}")
            self._log("=" * 60)

            self.worker_thread = threading.Thread(
                target=self._run_single_worker,
                args=(url, out_dir),
                daemon=True,
            )
            self.worker_thread.start()

        # Mode 3: Batch URL File
        elif active_tab_name == "Berkas Daftar URL":
            filepath = self.file_path_var.get().strip()
            if not filepath or not os.path.exists(filepath):
                messagebox.showwarning("Peringatan", f"Berkas daftar URL tidak ditemukan:\n{filepath}")
                return

            self._set_ui_state(True, status_text="MEMPROSES", badge_type="running")
            self.btn_stop.configure(text="Hentikan Proses")

            self._log("=" * 60)
            self._log(f"[INFO] Membaca berkas tautan: {engine.display_path(filepath)}")
            self._log(f"[INFO] Direktori simpan: {engine.display_path(out_dir)}")
            self._log("=" * 60)

            self.worker_thread = threading.Thread(
                target=self._run_file_worker,
                args=(filepath, out_dir, min_delay, max_delay),
                daemon=True,
            )
            self.worker_thread.start()

    # ---------------------------------------------------------------------------
    # Background Workers
    # ---------------------------------------------------------------------------
    def _run_multi_search_worker(self, keywords, limit, out_dir, min_delay, max_delay):
        old_stdout, old_stderr = sys.stdout, sys.stderr
        writer = QueueWriter(self.log_queue)
        sys.stdout, sys.stderr = writer, writer

        was_stopped = False
        try:
            stats = engine.search_and_bulk_download_keywords(
                keywords,
                limit_per_keyword=limit,
                output_dir=out_dir,
                min_delay=min_delay,
                max_delay=max_delay,
                stop_event=self.stop_event,
            )
            was_stopped = stats.get("stopped", False)
            if not was_stopped:
                self._open_output_folder()

        except Exception as exc:
            self._log(f"\n[ERROR] Terjadi kesalahan: {exc}")
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            status_text = "DIHENTIKAN" if was_stopped or self.stop_event.is_set() else "SELESAI"
            badge = "stopped" if was_stopped or self.stop_event.is_set() else "success"
            self.after(0, lambda: self._set_ui_state(False, status_text=status_text, badge_type=badge))

    def _run_single_worker(self, url, out_dir):
        old_stdout, old_stderr = sys.stdout, sys.stderr
        writer = QueueWriter(self.log_queue)
        sys.stdout, sys.stderr = writer, writer

        was_stopped = False
        try:
            saved_path, was_skipped = engine.download_scribd_document(
                url,
                output_dir=out_dir,
                close_driver=True,
                stop_event=self.stop_event,
            )
            if was_skipped:
                self._log(f"\n[INFO] Dokumen sudah pernah diunduh sebelumnya: {engine.display_path(saved_path)}")
            else:
                self._log(f"\n[SUKSES] Dokumen berhasil disimpan: {engine.display_path(saved_path)}")
            self._open_output_folder()

        except KeyboardInterrupt:
            was_stopped = True
            self._log("\n[STOP] Pengunduhan dokumen dihentikan oleh pengguna.")
        except Exception as exc:
            self._log(f"\n[ERROR] Gagal mengunduh dokumen: {exc}")
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            status_text = "DIHENTIKAN" if was_stopped or self.stop_event.is_set() else "SELESAI"
            badge = "stopped" if was_stopped or self.stop_event.is_set() else "success"
            self.after(0, lambda: self._set_ui_state(False, status_text=status_text, badge_type=badge))

    def _run_file_worker(self, filepath, out_dir, min_delay, max_delay):
        old_stdout, old_stderr = sys.stdout, sys.stderr
        writer = QueueWriter(self.log_queue)
        sys.stdout, sys.stderr = writer, writer

        try:
            urls = engine.load_urls_from_file(filepath)
            self._log(f"[INFO] Berhasil membaca {len(urls)} tautan dari berkas.")

            stats = engine.bulk_download_documents(
                urls,
                output_dir=out_dir,
                min_delay=min_delay,
                max_delay=max_delay,
                stop_event=self.stop_event,
            )
            self._open_output_folder()

        except Exception as exc:
            self._log(f"\n[ERROR] Gagal memproses berkas: {exc}")
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            status_text = "DIHENTIKAN" if self.stop_event.is_set() else "SELESAI"
            badge = "stopped" if self.stop_event.is_set() else "success"
            self.after(0, lambda: self._set_ui_state(False, status_text=status_text, badge_type=badge))


# ---------------------------------------------------------------------------
# Program Entry Point
# ---------------------------------------------------------------------------
def main():
    app = MomoRescribdApp()
    app.mainloop()


if __name__ == "__main__":
    main()
