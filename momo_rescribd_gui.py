#!/usr/bin/env python3
"""
Momo Rescribd — Desktop Interface for Scribd Bulk Search & Document Downloader.
Supports true parallel multi-keyword execution, dedicated per-keyword console tabs,
custom destination folders per keyword, and random delay range protection.
Cross-platform: macOS, Windows, and Linux.
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
# Cross-Platform Configurations & Styling
# ---------------------------------------------------------------------------
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

FONT_FAMILY_MAIN = "Segoe UI" if IS_WINDOWS else ("SF Pro Display" if IS_MAC else "Ubuntu")
FONT_FAMILY_MONO = "Consolas" if IS_WINDOWS else ("Menlo" if IS_MAC else "Monospace")

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ---------------------------------------------------------------------------
# Thread-Aware Stdout Router for 100% Isolated Concurrent Logging
# ---------------------------------------------------------------------------
class ThreadRoutedStdout:
    """
    Routes writes to the registered queue or handler of the calling thread.
    Prevents log interleaving when multiple keyword worker threads run concurrently.
    """

    def __init__(self, fallback_stream=None):
        self.fallback = fallback_stream or sys.__stdout__
        self._handlers = {}  # thread_ident -> queue or callable
        self._lock = threading.Lock()

    def register(self, thread_ident, target):
        with self._lock:
            self._handlers[thread_ident] = target

    def unregister(self, thread_ident):
        with self._lock:
            self._handlers.pop(thread_ident, None)

    def write(self, text):
        if not text:
            return
        tid = threading.get_ident()
        target = None
        with self._lock:
            target = self._handlers.get(tid)

        if target:
            try:
                if hasattr(target, "put"):
                    target.put(text)
                elif callable(target):
                    target(text)
            except Exception:
                if self.fallback:
                    self.fallback.write(text)
        else:
            if self.fallback:
                self.fallback.write(text)

    def flush(self):
        if self.fallback:
            self.fallback.flush()


# ---------------------------------------------------------------------------
# Task Item Model for Parallel Execution
# ---------------------------------------------------------------------------
class KeywordTask:
    """Represents a single keyword task card and its associated background worker."""

    def __init__(self, task_id, keyword, limit=5, folder=""):
        self.task_id = task_id
        self.keyword_var = tk.StringVar(value=keyword)
        self.limit_var = tk.StringVar(value=str(limit))
        self.folder_var = tk.StringVar(value=folder)
        self.status_var = tk.StringVar(value="SIAP")
        self.status_type = "ready"  # ready, running, success, stopped, error

        # Concurrency primitives
        self.thread = None
        self.stop_event = threading.Event()
        self.log_queue = queue.Queue()

        # UI Element References
        self.card_frame = None
        self.badge_label = None
        self.btn_stop = None
        self.btn_remove = None
        self.tab_name = None
        self.textbox = None


# ---------------------------------------------------------------------------
# Main Application Window
# ---------------------------------------------------------------------------
class MomoRescribdApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Momo Rescribd — Scribd Bulk Search & Document Downloader")
        self.geometry("1000x880")
        self.minsize(840, 720)

        # Set App Icon
        self._set_app_icon()

        # Setup Thread-Aware Stdout Router
        self.stdout_router = ThreadRoutedStdout(sys.__stdout__)
        sys.stdout = self.stdout_router
        sys.stderr = self.stdout_router

        # Global State Variables
        self.tasks = []
        self.task_counter = 0
        self.base_output_dir = os.path.expanduser("~/Downloads/Momo_Rescribd")
        self.min_delay_var = tk.StringVar(value="1.0")
        self.max_delay_var = tk.StringVar(value="5.0")
        self.base_folder_var = tk.StringVar(value=self.base_output_dir)

        # Single and File Mode Variables
        self.single_url_var = tk.StringVar(value="")
        self.file_path_var = tk.StringVar(value="")
        self.single_folder_var = tk.StringVar(value="")
        self.file_folder_var = tk.StringVar(value="")

        # Non-keyword worker references
        self.solo_thread = None
        self.solo_stop_event = threading.Event()
        self.solo_queue = queue.Queue()

        # Console Tab Tracking
        self.active_console_tabs = {}  # tab_name -> CTkTextbox

        self._build_ui()
        self._seed_sample_tasks()
        self._poll_log_queues()

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
    # UI Construction
    # ---------------------------------------------------------------------------
    def _build_ui(self):
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=20, pady=16)

        # 1. Header Area with Astronaut Mascot Logo
        self._build_header(self.main_container)

        # 2. Main Tabview (Pencarian Kata Kunci, Tautan Tunggal, Berkas URL)
        self._build_tabs(self.main_container)

        # 3. Settings Card (Delay Range & Default Folder)
        self._build_settings_card(self.main_container)

        # 4. Action Bar (Start All, Stop All, Open Base Folder, Progress Bar)
        self._build_action_bar(self.main_container)

        # 5. Dedicated Multi-Tab Console Card
        self._build_console_card(self.main_container)

    def _build_header(self, parent):
        header_frame = ctk.CTkFrame(parent, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 12))

        # Left Box: Logo & Titles
        left_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        left_box.pack(side="left", fill="y")

        base_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(base_dir, "assets", "logo.png")
        if os.path.exists(logo_path):
            try:
                pil_logo = Image.open(logo_path)
                self.logo_image = ctk.CTkImage(light_image=pil_logo, dark_image=pil_logo, size=(56, 56))
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
            text="Scribd Bulk Search & Document Downloader (Konkurensi Paralel)",
            font=(FONT_FAMILY_MAIN, 12),
            text_color="#94a3b8",
        )
        app_subtitle.pack(anchor="w", pady=(2, 0))

        # Right Box: Global Concurrency Status
        right_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        right_box.pack(side="right", fill="y")

        self.global_status_badge = ctk.CTkLabel(
            right_box,
            text="SIAP",
            font=(FONT_FAMILY_MAIN, 11, "bold"),
            text_color="#10b981",
            fg_color="#064e3b",
            corner_radius=8,
            padx=16,
            pady=6,
        )
        self.global_status_badge.pack(anchor="e", pady=(4, 0))

    def _build_tabs(self, parent):
        self.tabview = ctk.CTkTabview(parent, height=270, corner_radius=10)
        self.tabview.pack(fill="x", pady=(0, 10))

        # Tab 1: Parallel Keyword Tasks
        self.tab_search = self.tabview.add("Pencarian Kata Kunci")
        self._build_search_tab(self.tab_search)

        # Tab 2: Single URL
        self.tab_single = self.tabview.add("Tautan Tunggal")
        self._build_single_tab(self.tab_single)

        # Tab 3: URL List File
        self.tab_file = self.tabview.add("Berkas Daftar URL")
        self._build_file_tab(self.tab_file)

    def _build_search_tab(self, tab):
        # Top Controls Bar
        ctrl_bar = ctk.CTkFrame(tab, fg_color="transparent")
        ctrl_bar.pack(fill="x", pady=(0, 8))

        btn_add = ctk.CTkButton(
            ctrl_bar,
            text="+ Tambah Kata Kunci",
            width=150,
            height=28,
            font=(FONT_FAMILY_MAIN, 11, "bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self._add_empty_task,
        )
        btn_add.pack(side="left", padx=(0, 8))

        btn_paste = ctk.CTkButton(
            ctrl_bar,
            text="Tempel Banyak Teks...",
            width=140,
            height=28,
            font=(FONT_FAMILY_MAIN, 11),
            fg_color="#334155",
            hover_color="#475569",
            command=self._open_batch_import_dialog,
        )
        btn_paste.pack(side="left", padx=(0, 8))

        btn_reset = ctk.CTkButton(
            ctrl_bar,
            text="Reset Contoh",
            width=100,
            height=28,
            font=(FONT_FAMILY_MAIN, 11),
            fg_color="#334155",
            hover_color="#475569",
            command=self._reset_sample_tasks,
        )
        btn_reset.pack(side="left", padx=(0, 8))

        btn_clear = ctk.CTkButton(
            ctrl_bar,
            text="Hapus Semua",
            width=90,
            height=28,
            font=(FONT_FAMILY_MAIN, 11),
            fg_color="#1e293b",
            hover_color="#334155",
            command=self._clear_all_tasks,
        )
        btn_clear.pack(side="left")

        self.lbl_task_summary = ctk.CTkLabel(
            ctrl_bar,
            text="0 Tugas Terdaftar",
            font=(FONT_FAMILY_MAIN, 11, "bold"),
            text_color="#60a5fa",
        )
        self.lbl_task_summary.pack(side="right")

        # Scrollable Task Cards Container
        self.tasks_scroll = ctk.CTkScrollableFrame(
            tab,
            height=165,
            corner_radius=8,
            fg_color="#0f172a",
            border_width=1,
            border_color="#1e293b",
        )
        self.tasks_scroll.pack(fill="both", expand=True)

    def _build_single_tab(self, tab):
        lbl = ctk.CTkLabel(
            tab,
            text="Tautan Dokumen Scribd Spesifik:",
            font=(FONT_FAMILY_MAIN, 11, "bold"),
            text_color="#cbd5e1",
        )
        lbl.pack(anchor="w", pady=(4, 6))

        row1 = ctk.CTkFrame(tab, fg_color="transparent")
        row1.pack(fill="x", pady=(0, 8))

        self.entry_single_url = ctk.CTkEntry(
            row1,
            textvariable=self.single_url_var,
            placeholder_text="https://www.scribd.com/document/123456789/Judul-Dokumen",
            font=(FONT_FAMILY_MAIN, 12),
            height=32,
        )
        self.entry_single_url.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_paste = ctk.CTkButton(
            row1,
            text="Tempel",
            width=80,
            height=32,
            font=(FONT_FAMILY_MAIN, 11),
            fg_color="#334155",
            hover_color="#475569",
            command=self._paste_single_url,
        )
        btn_paste.pack(side="right")

        # Destination Folder for Single Mode
        row2 = ctk.CTkFrame(tab, fg_color="transparent")
        row2.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            row2,
            text="Folder Simpan:",
            font=(FONT_FAMILY_MAIN, 11),
            text_color="#cbd5e1",
            width=100,
            anchor="w",
        ).pack(side="left")

        self.entry_single_folder = ctk.CTkEntry(
            row2,
            textvariable=self.single_folder_var,
            placeholder_text="Kosongkan untuk otomatis ke folder Downloads/Momo_Rescribd",
            font=(FONT_FAMILY_MAIN, 11),
            height=30,
        )
        self.entry_single_folder.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_browse = ctk.CTkButton(
            row2,
            text="Pilih Folder...",
            width=100,
            height=30,
            font=(FONT_FAMILY_MAIN, 11),
            fg_color="#334155",
            hover_color="#475569",
            command=lambda: self._browse_custom_folder(self.single_folder_var),
        )
        btn_browse.pack(side="right")

        hint = ctk.CTkLabel(
            tab,
            text="Sistem akan mengonversi dokumen menjadi file PDF asli secara langsung tanpa batas halaman.",
            font=(FONT_FAMILY_MAIN, 10),
            text_color="#64748b",
        )
        hint.pack(anchor="w")

    def _build_file_tab(self, tab):
        lbl = ctk.CTkLabel(
            tab,
            text="Lokasi Berkas Teks Daftar URL (format satu tautan per baris):",
            font=(FONT_FAMILY_MAIN, 11, "bold"),
            text_color="#cbd5e1",
        )
        lbl.pack(anchor="w", pady=(4, 6))

        row1 = ctk.CTkFrame(tab, fg_color="transparent")
        row1.pack(fill="x", pady=(0, 8))

        self.entry_file_path = ctk.CTkEntry(
            row1,
            textvariable=self.file_path_var,
            placeholder_text="Pilih berkas urls.txt...",
            font=(FONT_FAMILY_MAIN, 12),
            height=32,
        )
        self.entry_file_path.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_browse_file = ctk.CTkButton(
            row1,
            text="Pilih Berkas...",
            width=110,
            height=32,
            font=(FONT_FAMILY_MAIN, 11),
            fg_color="#334155",
            hover_color="#475569",
            command=self._browse_file,
        )
        btn_browse_file.pack(side="right")

        # Destination Folder for File Mode
        row2 = ctk.CTkFrame(tab, fg_color="transparent")
        row2.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            row2,
            text="Folder Simpan:",
            font=(FONT_FAMILY_MAIN, 11),
            text_color="#cbd5e1",
            width=100,
            anchor="w",
        ).pack(side="left")

        self.entry_file_folder = ctk.CTkEntry(
            row2,
            textvariable=self.file_folder_var,
            placeholder_text="Kosongkan untuk otomatis ke folder Downloads/Momo_Rescribd",
            font=(FONT_FAMILY_MAIN, 11),
            height=30,
        )
        self.entry_file_folder.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_browse_folder = ctk.CTkButton(
            row2,
            text="Pilih Folder...",
            width=100,
            height=30,
            font=(FONT_FAMILY_MAIN, 11),
            fg_color="#334155",
            hover_color="#475569",
            command=lambda: self._browse_custom_folder(self.file_folder_var),
        )
        btn_browse_folder.pack(side="right")

    def _build_settings_card(self, parent):
        card = ctk.CTkFrame(parent, corner_radius=10, fg_color="#1e293b", border_width=1, border_color="#334155")
        card.pack(fill="x", pady=(0, 10), padx=2, ipady=4)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=10)

        # Row 1: Delay and Base Folder
        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x")

        # Delay
        ctk.CTkLabel(
            row,
            text="Jeda Acak (detik):",
            font=(FONT_FAMILY_MAIN, 11, "bold"),
            text_color="#f8fafc",
        ).pack(side="left", padx=(0, 8))

        entry_min = ctk.CTkEntry(
            row,
            textvariable=self.min_delay_var,
            width=46,
            height=28,
            justify="center",
            font=(FONT_FAMILY_MAIN, 11),
        )
        entry_min.pack(side="left")

        ctk.CTkLabel(row, text="s/d", font=(FONT_FAMILY_MAIN, 11), text_color="#94a3b8").pack(side="left", padx=6)

        entry_max = ctk.CTkEntry(
            row,
            textvariable=self.max_delay_var,
            width=46,
            height=28,
            justify="center",
            font=(FONT_FAMILY_MAIN, 11),
        )
        entry_max.pack(side="left")

        ctk.CTkLabel(
            row,
            text="(1000 - 5000 ms perlindungan rate-limit)",
            font=(FONT_FAMILY_MAIN, 10),
            text_color="#64748b",
        ).pack(side="left", padx=(8, 20))

        # Base Output Folder
        ctk.CTkLabel(
            row,
            text="Folder Utama:",
            font=(FONT_FAMILY_MAIN, 11, "bold"),
            text_color="#f8fafc",
        ).pack(side="left", padx=(0, 8))

        entry_base = ctk.CTkEntry(
            row,
            textvariable=self.base_folder_var,
            font=(FONT_FAMILY_MAIN, 11),
            height=28,
        )
        entry_base.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_base = ctk.CTkButton(
            row,
            text="Pilih...",
            width=70,
            height=28,
            font=(FONT_FAMILY_MAIN, 11),
            fg_color="#334155",
            hover_color="#475569",
            command=self._browse_base_folder,
        )
        btn_base.pack(side="right")

    def _build_action_bar(self, parent):
        action_row = ctk.CTkFrame(parent, fg_color="transparent")
        action_row.pack(fill="x", pady=(0, 10))

        # Start All Button
        self.btn_start_all = ctk.CTkButton(
            action_row,
            text="Mulai Semua Bersamaan",
            font=(FONT_FAMILY_MAIN, 12, "bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            height=38,
            width=180,
            corner_radius=8,
            command=self._start_all_processes,
        )
        self.btn_start_all.pack(side="left", padx=(0, 10))

        # Stop All Button
        self.btn_stop_all = ctk.CTkButton(
            action_row,
            text="Hentikan Semua",
            font=(FONT_FAMILY_MAIN, 12, "bold"),
            fg_color="#dc2626",
            hover_color="#b91c1c",
            height=38,
            width=140,
            corner_radius=8,
            state="disabled",
            command=self._stop_all_processes,
        )
        self.btn_stop_all.pack(side="left", padx=(0, 10))

        # Open Base Folder Button
        self.btn_open_base = ctk.CTkButton(
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
            command=self._open_base_folder,
        )
        self.btn_open_base.pack(side="left")

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
        console_card = ctk.CTkFrame(
            parent,
            corner_radius=10,
            fg_color="#0b0f19",
            border_width=1,
            border_color="#1e293b",
        )
        console_card.pack(fill="both", expand=True)

        # Top Bar of Console Card
        top_bar = ctk.CTkFrame(console_card, height=36, fg_color="#111827", corner_radius=0)
        top_bar.pack(fill="x", padx=1, pady=1)

        ctk.CTkLabel(
            top_bar,
            text="Konsol Aktivitas per Kata Kunci (Terisolasi)",
            font=(FONT_FAMILY_MAIN, 11, "bold"),
            text_color="#94a3b8",
        ).pack(side="left", padx=12, pady=4)

        btn_copy = ctk.CTkButton(
            top_bar,
            text="Salin Log Tab Ini",
            width=110,
            height=24,
            font=(FONT_FAMILY_MAIN, 10),
            fg_color="#1f2937",
            hover_color="#374151",
            command=self._copy_active_tab_log,
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
            command=self._clear_active_tab_log,
        )
        btn_clear.pack(side="right", padx=(6, 0), pady=4)

        btn_open_tab_folder = ctk.CTkButton(
            top_bar,
            text="Buka Folder Tab",
            width=110,
            height=24,
            font=(FONT_FAMILY_MAIN, 10),
            fg_color="#1f2937",
            hover_color="#374151",
            command=self._open_active_tab_folder,
        )
        btn_open_tab_folder.pack(side="right", pady=4)

        # Dynamic Console Tabview
        self.console_tabview = ctk.CTkTabview(
            console_card,
            corner_radius=8,
            fg_color="#0b0f19",
        )
        self.console_tabview.pack(fill="both", expand=True, padx=6, pady=(0, 6))

    # ---------------------------------------------------------------------------
    # Task Management & Dynamic UI Cards
    # ---------------------------------------------------------------------------
    def _seed_sample_tasks(self):
        sample_kws = ["Petrokimia Gresik", "Pupuk Kaltim", "Pupuk Indonesia"]
        for kw in sample_kws:
            self._create_task(kw, limit=5)
        self._sync_task_summary()

    def _reset_sample_tasks(self):
        if self._any_task_running():
            messagebox.showwarning("Peringatan", "Tidak dapat mereset saat proses masih berjalan.")
            return
        self._clear_all_tasks()
        self._seed_sample_tasks()

    def _clear_all_tasks(self):
        if self._any_task_running():
            messagebox.showwarning("Peringatan", "Harap hentikan semua tugas yang sedang berjalan terlebih dahulu.")
            return
        for task in list(self.tasks):
            self._remove_task(task)
        self._sync_task_summary()

    def _add_empty_task(self):
        idx = len(self.tasks) + 1
        self._create_task(f"Kata Kunci {idx}", limit=5)
        self._sync_task_summary()

    def _create_task(self, keyword, limit=5, folder=""):
        self.task_counter += 1
        task_id = f"task_{self.task_counter}"

        # Default folder if none provided
        if not folder:
            clean_slug = re.sub(r"[^\w\-]", "_", keyword.strip()).strip("_") or f"task_{self.task_counter}"
            folder = os.path.join(self._get_base_folder(), clean_slug)

        task = KeywordTask(task_id, keyword, limit, folder)

        # Build Card Widget in tasks_scroll
        card = ctk.CTkFrame(
            self.tasks_scroll,
            corner_radius=8,
            fg_color="#1e293b",
            border_width=1,
            border_color="#334155",
        )
        card.pack(fill="x", pady=4, padx=2)
        task.card_frame = card

        # Row 1: Keyword, Target, Status Badge, Stop & Remove Buttons
        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", padx=10, pady=(8, 4))

        lbl_idx = ctk.CTkLabel(
            row1,
            text=f"[{len(self.tasks) + 1}]",
            font=(FONT_FAMILY_MAIN, 11, "bold"),
            text_color="#94a3b8",
            width=28,
        )
        lbl_idx.pack(side="left", padx=(0, 6))

        entry_kw = ctk.CTkEntry(
            row1,
            textvariable=task.keyword_var,
            placeholder_text="Masukkan kata kunci...",
            font=(FONT_FAMILY_MAIN, 12, "bold"),
            height=28,
            width=240,
        )
        entry_kw.pack(side="left", padx=(0, 10))
        entry_kw.bind("<KeyRelease>", lambda e, t=task: self._on_task_keyword_change(t))

        ctk.CTkLabel(
            row1,
            text="Target:",
            font=(FONT_FAMILY_MAIN, 11),
            text_color="#cbd5e1",
        ).pack(side="left", padx=(0, 4))

        entry_lim = ctk.CTkEntry(
            row1,
            textvariable=task.limit_var,
            font=(FONT_FAMILY_MAIN, 11),
            height=28,
            width=48,
            justify="center",
        )
        entry_lim.pack(side="left", padx=(0, 4))

        ctk.CTkLabel(
            row1,
            text="dokumen",
            font=(FONT_FAMILY_MAIN, 11),
            text_color="#94a3b8",
        ).pack(side="left", padx=(0, 12))

        # Status Badge
        badge = ctk.CTkLabel(
            row1,
            text="SIAP",
            font=(FONT_FAMILY_MAIN, 10, "bold"),
            text_color="#10b981",
            fg_color="#064e3b",
            corner_radius=6,
            padx=10,
            pady=3,
        )
        badge.pack(side="left", padx=(0, 8))
        task.badge_label = badge

        # Remove Task Button
        btn_del = ctk.CTkButton(
            row1,
            text="Hapus",
            width=55,
            height=26,
            font=(FONT_FAMILY_MAIN, 10),
            fg_color="#334155",
            hover_color="#475569",
            command=lambda t=task: self._remove_task(t),
        )
        btn_del.pack(side="right")
        task.btn_remove = btn_del

        # Stop Task Button
        btn_stop = ctk.CTkButton(
            row1,
            text="Hentikan",
            width=70,
            height=26,
            font=(FONT_FAMILY_MAIN, 10, "bold"),
            fg_color="#475569",
            hover_color="#b91c1c",
            state="disabled",
            command=lambda t=task: self._stop_single_task(t),
        )
        btn_stop.pack(side="right", padx=(0, 6))
        task.btn_stop = btn_stop

        # Row 2: Destination Folder & Browse Button
        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=10, pady=(0, 8))

        ctk.CTkLabel(
            row2,
            text="Folder Simpan:",
            font=(FONT_FAMILY_MAIN, 10),
            text_color="#94a3b8",
            width=80,
            anchor="w",
        ).pack(side="left", padx=(34, 4))

        entry_folder = ctk.CTkEntry(
            row2,
            textvariable=task.folder_var,
            font=(FONT_FAMILY_MAIN, 10),
            height=26,
        )
        entry_folder.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_browse_task_folder = ctk.CTkButton(
            row2,
            text="Pilih Folder...",
            width=90,
            height=26,
            font=(FONT_FAMILY_MAIN, 10),
            fg_color="#334155",
            hover_color="#475569",
            command=lambda t=task: self._browse_custom_folder(t.folder_var),
        )
        btn_browse_task_folder.pack(side="left", padx=(0, 4))

        btn_open_card_folder = ctk.CTkButton(
            row2,
            text="Buka",
            width=50,
            height=26,
            font=(FONT_FAMILY_MAIN, 10),
            fg_color="#1e293b",
            hover_color="#334155",
            command=lambda t=task: self._open_task_folder(t),
        )
        btn_open_card_folder.pack(side="left")

        self.tasks.append(task)
        self._ensure_console_tab_for_task(task)
        return task

    def _on_task_keyword_change(self, task):
        # Auto update folder if it was still following default slug pattern
        kw = task.keyword_var.get().strip()
        cur_folder = task.folder_var.get().strip()
        base = self._get_base_folder()

        if not cur_folder or cur_folder.startswith(base):
            slug = re.sub(r"[^\w\-]", "_", kw).strip("_") if kw else f"task_{task.task_id}"
            task.folder_var.set(os.path.join(base, slug))

        # Rename console tab if idle
        if not (task.thread and task.thread.is_alive()):
            self._ensure_console_tab_for_task(task)

    def _remove_task(self, task):
        if task.thread and task.thread.is_alive():
            messagebox.showwarning("Peringatan", "Tugas sedang berjalan. Hentikan tugas terlebih dahulu.")
            return

        if task.card_frame:
            task.card_frame.destroy()

        # Remove console tab if exists
        if task.tab_name and task.tab_name in self.active_console_tabs:
            try:
                self.console_tabview.delete(task.tab_name)
            except Exception:
                pass
            self.active_console_tabs.pop(task.tab_name, None)

        if task in self.tasks:
            self.tasks.remove(task)

        self._sync_task_summary()

    def _sync_task_summary(self):
        total = len(self.tasks)
        running = sum(1 for t in self.tasks if t.thread and t.thread.is_alive())
        if total == 0:
            self.lbl_task_summary.configure(text="Belum ada tugas", text_color="#ef4444")
        elif running > 0:
            self.lbl_task_summary.configure(
                text=f"{running} Berjalan, {total - running} Selesai/Siap",
                text_color="#f59e0b",
            )
        else:
            self.lbl_task_summary.configure(
                text=f"{total} Tugas Siap Dijalankan",
                text_color="#60a5fa",
            )

    def _ensure_console_tab_for_task(self, task):
        kw = task.keyword_var.get().strip() or f"Tugas {task.task_id}"
        # Truncate tab title cleanly
        clean_name = kw[:24].strip()

        # If tab exists and name didn't change, return
        if task.tab_name == clean_name and clean_name in self.active_console_tabs:
            return

        # If had an old tab name, delete it
        if task.tab_name and task.tab_name != clean_name and task.tab_name in self.active_console_tabs:
            try:
                self.console_tabview.delete(task.tab_name)
            except Exception:
                pass
            self.active_console_tabs.pop(task.tab_name, None)

        # Create new tab if not present
        if clean_name not in self.active_console_tabs:
            try:
                tab_frame = self.console_tabview.add(clean_name)
            except Exception:
                # Tab with this name already exists in widget
                clean_name = f"{clean_name} ({task.task_id})"
                try:
                    tab_frame = self.console_tabview.add(clean_name)
                except Exception:
                    return

            tb = ctk.CTkTextbox(
                tab_frame,
                font=(FONT_FAMILY_MONO, 11),
                text_color="#e2e8f0",
                fg_color="#0b0f19",
                wrap="word",
                corner_radius=6,
            )
            tb.pack(fill="both", expand=True, padx=4, pady=4)
            tb.insert(
                "end",
                f"[INFO] Konsol terisolasi untuk kata kunci: '{kw}'\n"
                f"[INFO] File PDF akan disimpan ke: {engine.display_path(task.folder_var.get().strip())}\n\n",
            )
            self.active_console_tabs[clean_name] = tb
            task.tab_name = clean_name
            task.textbox = tb
        else:
            task.tab_name = clean_name
            task.textbox = self.active_console_tabs[clean_name]

    def _open_batch_import_dialog(self):
        """Allows user to paste multiple lines of keywords to generate cards automatically."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Tempel Banyak Kata Kunci")
        dialog.geometry("520x400")
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog,
            text="Tempel daftar kata kunci (satu per baris):",
            font=(FONT_FAMILY_MAIN, 12, "bold"),
            text_color="#f8fafc",
        ).pack(anchor="w", padx=16, pady=(16, 6))

        tb = ctk.CTkTextbox(dialog, height=220, font=(FONT_FAMILY_MAIN, 12))
        tb.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        tb.insert("1.0", "Petrokimia Gresik\nPupuk Kaltim\nPupuk Indonesia")

        btn_box = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_box.pack(fill="x", padx=16, pady=(0, 16))

        def _do_import():
            raw = tb.get("1.0", "end").strip()
            lines = [line.strip() for line in raw.split("\n") if line.strip()]
            if lines:
                for line in lines:
                    self._create_task(line, limit=5)
                self._sync_task_summary()
            dialog.destroy()

        ctk.CTkButton(
            btn_box,
            text="Tambahkan ke Daftar",
            font=(FONT_FAMILY_MAIN, 11, "bold"),
            fg_color="#2563eb",
            command=_do_import,
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_box,
            text="Batal",
            font=(FONT_FAMILY_MAIN, 11),
            fg_color="#334155",
            command=dialog.destroy,
        ).pack(side="right")

    # ---------------------------------------------------------------------------
    # Folder & Path Helpers
    # ---------------------------------------------------------------------------
    def _get_base_folder(self):
        val = self.base_folder_var.get().strip()
        if val:
            p = os.path.expanduser(val)
        else:
            p = os.path.expanduser("~/Downloads/Momo_Rescribd")
        os.makedirs(p, exist_ok=True)
        return p

    def _browse_base_folder(self):
        cur = self._get_base_folder()
        d = filedialog.askdirectory(title="Pilih Folder Penyimpanan Utama", initialdir=cur)
        if d:
            self.base_folder_var.set(d)

    def _browse_custom_folder(self, string_var):
        cur = string_var.get().strip() or self._get_base_folder()
        d = filedialog.askdirectory(title="Pilih Folder Simpan Dokumen", initialdir=cur)
        if d:
            string_var.set(d)

    def _open_task_folder(self, task):
        folder = os.path.expanduser(task.folder_var.get().strip())
        if not folder:
            folder = self._get_base_folder()
        os.makedirs(folder, exist_ok=True)
        if not engine.open_in_file_manager(folder):
            messagebox.showinfo("Informasi", f"Folder belum ada atau gagal dibuka:\n{engine.display_path(folder)}")

    def _open_base_folder(self):
        base = self._get_base_folder()
        if not engine.open_in_file_manager(base):
            messagebox.showinfo("Informasi", f"Folder belum ada atau gagal dibuka:\n{engine.display_path(base)}")

    def _browse_file(self):
        f = filedialog.askopenfilename(
            title="Pilih Berkas Teks Daftar URL",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
        )
        if f:
            self.file_path_var.set(f)

    def _paste_single_url(self):
        try:
            clipboard = self.clipboard_get()
            self.single_url_var.set(clipboard.strip())
        except Exception:
            pass

    # ---------------------------------------------------------------------------
    # Console Tab Actions & Real-Time Queue Polling
    # ---------------------------------------------------------------------------
    def _get_active_tab_name(self):
        try:
            return self.console_tabview.get()
        except Exception:
            return None

    def _copy_active_tab_log(self):
        tab_name = self._get_active_tab_name()
        if tab_name and tab_name in self.active_console_tabs:
            tb = self.active_console_tabs[tab_name]
            content = tb.get("1.0", "end")
            self.clipboard_clear()
            self.clipboard_append(content)
            messagebox.showinfo("Sukses", f"Log untuk '{tab_name}' berhasil disalin ke clipboard.")

    def _clear_active_tab_log(self):
        tab_name = self._get_active_tab_name()
        if tab_name and tab_name in self.active_console_tabs:
            tb = self.active_console_tabs[tab_name]
            tb.delete("1.0", "end")

    def _open_active_tab_folder(self):
        tab_name = self._get_active_tab_name()
        # Look for matching task
        for t in self.tasks:
            if t.tab_name == tab_name:
                self._open_task_folder(t)
                return
        self._open_base_folder()

    def _poll_log_queues(self):
        """Drains log queues for all active tasks and inserts text into dedicated textboxes."""
        for task in self.tasks:
            if not task.log_queue.empty() and task.textbox:
                try:
                    while not task.log_queue.empty():
                        msg = task.log_queue.get_nowait()
                        task.textbox.insert("end", msg)
                    task.textbox.see("end")
                except Exception:
                    pass

        # Also drain solo queue if active
        if not self.solo_queue.empty():
            active_name = self._get_active_tab_name()
            tb = self.active_console_tabs.get(active_name)
            while not self.solo_queue.empty():
                try:
                    msg = self.solo_queue.get_nowait()
                    if tb:
                        tb.insert("end", msg)
                except Exception:
                    break
            if tb:
                tb.see("end")

        self.after(50, self._poll_log_queues)

    # ---------------------------------------------------------------------------
    # Concurrency Execution & Process Handlers
    # ---------------------------------------------------------------------------
    def _any_task_running(self):
        if self.solo_thread and self.solo_thread.is_alive():
            return True
        return any(t.thread and t.thread.is_alive() for t in self.tasks)

    def _update_global_ui_state(self):
        running = self._any_task_running()
        if running:
            self.btn_start_all.configure(state="disabled", fg_color="#475569")
            self.btn_stop_all.configure(state="normal", fg_color="#dc2626")
            self.progress_bar.start()

            active_count = sum(1 for t in self.tasks if t.thread and t.thread.is_alive())
            if active_count > 0:
                self.global_status_badge.configure(
                    text=f"{active_count} BERJALAN",
                    text_color="#f59e0b",
                    fg_color="#78350f",
                )
            else:
                self.global_status_badge.configure(
                    text="BERJALAN",
                    text_color="#f59e0b",
                    fg_color="#78350f",
                )
        else:
            self.btn_start_all.configure(state="normal", fg_color="#2563eb")
            self.btn_stop_all.configure(state="disabled", fg_color="#475569")
            self.progress_bar.stop()
            self.progress_bar.set(0)

            # Check if any task was stopped or error
            any_stopped = any(t.status_type == "stopped" for t in self.tasks)
            all_done = bool(self.tasks) and all(t.status_type in ("success", "stopped") for t in self.tasks)

            if any_stopped:
                self.global_status_badge.configure(
                    text="DIHENTIKAN",
                    text_color="#ef4444",
                    fg_color="#7f1d1d",
                )
            elif all_done:
                self.global_status_badge.configure(
                    text="SELESAI",
                    text_color="#38bdf8",
                    fg_color="#0c4a6e",
                )
            else:
                self.global_status_badge.configure(
                    text="SIAP",
                    text_color="#10b981",
                    fg_color="#064e3b",
                )

        self._sync_task_summary()

    def _set_task_status(self, task, text, badge_type="ready"):
        task.status_var.set(text)
        task.status_type = badge_type

        badge_configs = {
            "ready": ("#10b981", "#064e3b"),
            "running": ("#f59e0b", "#78350f"),
            "downloading": ("#38bdf8", "#0c4a6e"),
            "stopped": ("#ef4444", "#7f1d1d"),
            "success": ("#34d399", "#065f46"),
            "error": ("#ef4444", "#7f1d1d"),
        }
        fg_col, bg_col = badge_configs.get(badge_type, ("#10b981", "#064e3b"))
        if task.badge_label:
            task.badge_label.configure(text=text, text_color=fg_col, fg_color=bg_col)

        if badge_type in ("running", "downloading"):
            if task.btn_stop:
                task.btn_stop.configure(state="normal", fg_color="#dc2626")
            if task.btn_remove:
                task.btn_remove.configure(state="disabled")
        else:
            if task.btn_stop:
                task.btn_stop.configure(state="disabled", fg_color="#475569")
            if task.btn_remove:
                task.btn_remove.configure(state="normal")

    def _stop_single_task(self, task):
        if task.thread and task.thread.is_alive():
            task.stop_event.set()
            task.log_queue.put("\n[STOP] Sinyal henti dikirim untuk tugas ini...\n")
            if task.btn_stop:
                task.btn_stop.configure(state="disabled", text="MENGHENTIKAN")
            self._set_task_status(task, "MENGHENTIKAN", badge_type="stopped")

    def _stop_all_processes(self):
        # Stop all keyword tasks
        for task in self.tasks:
            if task.thread and task.thread.is_alive():
                task.stop_event.set()
                task.log_queue.put("\n[STOP] Sinyal henti global dikirim untuk tugas ini...\n")
                if task.btn_stop:
                    task.btn_stop.configure(state="disabled")

        # Stop solo thread if active
        if self.solo_thread and self.solo_thread.is_alive():
            self.solo_stop_event.set()
            self.solo_queue.put("\n[STOP] Sinyal henti dikirim...\n")

        self.btn_stop_all.configure(state="disabled", text="MENGHENTIKAN...")

    def _start_all_processes(self):
        if self._any_task_running():
            return

        active_tab_mode = self.tabview.get()

        # Parse Global Delay Range
        try:
            min_delay = max(0.5, float(self.min_delay_var.get().strip()))
            max_delay = max(min_delay, float(self.max_delay_var.get().strip()))
        except Exception:
            min_delay = 1.0
            max_delay = 5.0
            self.min_delay_var.set("1.0")
            self.max_delay_var.set("5.0")

        # Mode 1: Parallel Keyword Tasks
        if active_tab_mode == "Pencarian Kata Kunci":
            if not self.tasks:
                messagebox.showwarning("Peringatan", "Silakan tambahkan minimal satu kata kunci.")
                return

            valid_tasks = []
            for task in self.tasks:
                kw = task.keyword_var.get().strip()
                if kw:
                    valid_tasks.append(task)

            if not valid_tasks:
                messagebox.showwarning("Peringatan", "Semua baris kata kunci masih kosong.")
                return

            # Launch all tasks simultaneously in separate threads
            for task in valid_tasks:
                self._ensure_console_tab_for_task(task)
                task.stop_event.clear()
                if task.btn_stop:
                    task.btn_stop.configure(text="Hentikan")

                # Parse task limit
                try:
                    limit = max(1, int(task.limit_var.get().strip()))
                except Exception:
                    limit = 5
                    task.limit_var.set("5")

                # Destination Folder for this task
                out_dir = task.folder_var.get().strip()
                if not out_dir:
                    clean_slug = re.sub(r"[^\w\-]", "_", task.keyword_var.get().strip()).strip("_")
                    out_dir = os.path.join(self._get_base_folder(), clean_slug)
                    task.folder_var.set(out_dir)

                self._set_task_status(task, "MENCARI", badge_type="running")

                # Launch concurrent worker thread
                t = threading.Thread(
                    target=self._parallel_keyword_worker,
                    args=(task, limit, out_dir, min_delay, max_delay),
                    daemon=True,
                )
                task.thread = t
                t.start()

            # Switch console tabview to the first running task
            first_tab = valid_tasks[0].tab_name
            if first_tab:
                try:
                    self.console_tabview.set(first_tab)
                except Exception:
                    pass

            self._update_global_ui_state()

        # Mode 2: Single URL Mode
        elif active_tab_mode == "Tautan Tunggal":
            url = self.single_url_var.get().strip()
            if not url:
                messagebox.showwarning("Peringatan", "Silakan masukkan tautan dokumen Scribd.")
                return

            out_dir = self.single_folder_var.get().strip() or self._get_base_folder()
            self._ensure_solo_tab("Tautan Tunggal")

            self.solo_stop_event.clear()
            self.solo_thread = threading.Thread(
                target=self._solo_single_worker,
                args=(url, out_dir),
                daemon=True,
            )
            self.solo_thread.start()
            self._update_global_ui_state()

        # Mode 3: URL List File Mode
        elif active_tab_mode == "Berkas Daftar URL":
            fpath = self.file_path_var.get().strip()
            if not fpath or not os.path.exists(fpath):
                messagebox.showwarning("Peringatan", f"Berkas tidak ditemukan:\n{fpath}")
                return

            out_dir = self.file_folder_var.get().strip() or self._get_base_folder()
            self._ensure_solo_tab("Berkas URL")

            self.solo_stop_event.clear()
            self.solo_thread = threading.Thread(
                target=self._solo_file_worker,
                args=(fpath, out_dir, min_delay, max_delay),
                daemon=True,
            )
            self.solo_thread.start()
            self._update_global_ui_state()

    def _ensure_solo_tab(self, tab_name):
        if tab_name not in self.active_console_tabs:
            tab_frame = self.console_tabview.add(tab_name)
            tb = ctk.CTkTextbox(
                tab_frame,
                font=(FONT_FAMILY_MONO, 11),
                text_color="#e2e8f0",
                fg_color="#0b0f19",
                wrap="word",
                corner_radius=6,
            )
            tb.pack(fill="both", expand=True, padx=4, pady=4)
            self.active_console_tabs[tab_name] = tb
        try:
            self.console_tabview.set(tab_name)
        except Exception:
            pass

    # ---------------------------------------------------------------------------
    # Worker Functions
    # ---------------------------------------------------------------------------
    def _parallel_keyword_worker(self, task, limit, out_dir, min_delay, max_delay):
        tid = threading.get_ident()
        # Register this thread with its private log queue
        self.stdout_router.register(tid, task.log_queue)

        kw = task.keyword_var.get().strip()

        def status_cb(stage, details):
            if stage == "MENCARI":
                self.after(0, lambda: self._set_task_status(task, "MENCARI", badge_type="running"))
            elif stage == "MENGUNDUH":
                self.after(0, lambda: self._set_task_status(task, "MENGUNDUH", badge_type="downloading"))
            elif stage == "SELESAI":
                self.after(0, lambda: self._set_task_status(task, "SELESAI", badge_type="success"))
            elif stage == "DIHENTIKAN":
                self.after(0, lambda: self._set_task_status(task, "DIHENTIKAN", badge_type="stopped"))

        try:
            stats = engine.run_keyword_task(
                keyword=kw,
                limit=limit,
                output_dir=out_dir,
                min_delay=min_delay,
                max_delay=max_delay,
                stop_event=task.stop_event,
                status_callback=status_cb,
            )
            was_stopped = stats.get("stopped", False)
            badge_type = "stopped" if was_stopped or task.stop_event.is_set() else "success"
            status_text = "DIHENTIKAN" if badge_type == "stopped" else "SELESAI"
            self.after(0, lambda: self._set_task_status(task, status_text, badge_type=badge_type))

        except Exception as exc:
            task.log_queue.put(f"\n[ERROR] Terjadi kesalahan pada tugas '{kw}': {exc}\n")
            self.after(0, lambda: self._set_task_status(task, "ERROR", badge_type="error"))
        finally:
            self.stdout_router.unregister(tid)
            self.after(0, self._update_global_ui_state)

    def _solo_single_worker(self, url, out_dir):
        tid = threading.get_ident()
        self.stdout_router.register(tid, self.solo_queue)
        try:
            print("=" * 60)
            print(f"[INFO] Mengunduh dokumen dari URL: {url}")
            print(f"[INFO] Folder simpan: {engine.display_path(out_dir)}")
            print("=" * 60 + "\n")

            saved_path, was_skipped = engine.download_scribd_document(
                url,
                output_dir=out_dir,
                close_driver=True,
                stop_event=self.solo_stop_event,
            )
            if was_skipped:
                print(f"\n[LEWATI] Dokumen sudah ada sebelumnya: {engine.display_path(saved_path)}")
            else:
                print(f"\n[SUKSES] Dokumen berhasil disimpan: {engine.display_path(saved_path)}")
        except Exception as exc:
            print(f"\n[ERROR] Gagal mengunduh dokumen: {exc}")
        finally:
            self.stdout_router.unregister(tid)
            self.after(0, self._update_global_ui_state)

    def _solo_file_worker(self, fpath, out_dir, min_delay, max_delay):
        tid = threading.get_ident()
        self.stdout_router.register(tid, self.solo_queue)
        try:
            urls = engine.load_urls_from_file(fpath)
            print("=" * 60)
            print(f"[INFO] Membaca {len(urls)} tautan dari berkas: {engine.display_path(fpath)}")
            print(f"[INFO] Folder simpan: {engine.display_path(out_dir)}")
            print("=" * 60 + "\n")

            stats = engine.bulk_download_documents(
                urls,
                output_dir=out_dir,
                min_delay=min_delay,
                max_delay=max_delay,
                stop_event=self.solo_stop_event,
            )
        except Exception as exc:
            print(f"\n[ERROR] Gagal memproses berkas: {exc}")
        finally:
            self.stdout_router.unregister(tid)
            self.after(0, self._update_global_ui_state)


# ---------------------------------------------------------------------------
# Application Entry Point
# ---------------------------------------------------------------------------
def main():
    app = MomoRescribdApp()
    app.mainloop()


if __name__ == "__main__":
    main()
