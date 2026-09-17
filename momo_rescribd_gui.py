#!/usr/bin/env python3
"""
Momo Rescribd — Desktop Interface for Scribd Bulk Search & Document Downloader.
True parallel multi-keyword execution, dedicated per-keyword console tabs,
custom destination folders per keyword, live per-card progress bars,
and robust macOS trackpad click handling.
Cross-platform: macOS, Windows, and Linux.
"""

import logging
import multiprocessing
import os
import queue
import random
import re
import sys
import tempfile
import threading
import time
import tkinter as tk
import traceback
from logging.handlers import RotatingFileHandler
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

import scribd_engine as engine
from research_panel import TAB_NAME as RESEARCH_TAB_NAME, ResearchPanel


# ---------------------------------------------------------------------------
# Cross-Platform Configurations & Styling
# ---------------------------------------------------------------------------
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"


# ---------------------------------------------------------------------------
# Crash & Diagnostics Logging
# ---------------------------------------------------------------------------
# A windowed .app bundle has no terminal attached, so anything written to
# stdout/stderr is lost. Without a real sink, an exception raised inside a
# button's command produces zero feedback and the button simply looks dead.
# Every diagnostic therefore goes to a file the user can be pointed at.
MAX_LOG_BYTES = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 2


def _resolve_log_path():
    if IS_WINDOWS:
        base = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "MomoRescribd")
    elif IS_MAC:
        base = os.path.expanduser("~/Library/Logs/MomoRescribd")
    else:
        base = os.path.expanduser("~/.local/state/momo-rescribd")
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        base = tempfile.gettempdir()
    return os.path.join(base, "momo_rescribd.log")


LOG_PATH = _resolve_log_path()


def _setup_logging():
    logger = logging.getLogger("momo_rescribd")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    try:
        handler = RotatingFileHandler(
            LOG_PATH, maxBytes=MAX_LOG_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s"))
        logger.addHandler(handler)
    except OSError:
        logger.addHandler(logging.NullHandler())
    return logger


LOGGER = _setup_logging()

FONT_FAMILY_MAIN = "Segoe UI" if IS_WINDOWS else ("SF Pro Display" if IS_MAC else "Ubuntu")
FONT_FAMILY_MONO = "Consolas" if IS_WINDOWS else ("Menlo" if IS_MAC else "Monospace")

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ---------------------------------------------------------------------------
# macOS Trackpad / Mouse Click Responsiveness Patch
# ---------------------------------------------------------------------------
# CustomTkinter decides whether to fire a button's command by reading
# _mouse_inside, which <Leave> resets to False. On macOS, trackpad micro-motion
# fires <Leave> between press and release, so the click is silently dropped.
#
# The fix binds <Button-1> to force _mouse_inside = True the instant the button
# is pressed. It MUST be applied from _draw(), not _create_bindings():
# CTkButton.__init__ calls _create_bindings() while _text_label and
# _image_label are still None (they are created later, inside _draw), and
# _draw never calls _create_bindings again. Patching _create_bindings therefore
# only ever reaches the canvas -- leaving the text label, which covers the
# centre of the button, on the old click-dropping path.
_orig_ctk_button_draw = ctk.CTkButton._draw

_PRESS_BOUND_FLAG = "_momo_press_bound"


def _ensure_press_binding(button):
    """Bind <Button-1> on the canvas and on both labels, exactly once each."""

    def _on_press(event=None):
        if button._state not in ("disabled", tk.DISABLED):
            button._mouse_inside = True

    for widget in (button._canvas, button._text_label, button._image_label):
        if widget is None or getattr(widget, _PRESS_BOUND_FLAG, False):
            continue
        widget.bind("<Button-1>", _on_press, add=True)
        setattr(widget, _PRESS_BOUND_FLAG, True)


def _patched_ctk_button_draw(self, no_color_updates=False):
    _orig_ctk_button_draw(self, no_color_updates)
    # _draw runs again whenever the text/image labels are recreated, so this
    # re-binds them without duplicating handlers on widgets already covered.
    _ensure_press_binding(self)


ctk.CTkButton._draw = _patched_ctk_button_draw


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

    def _write_fallback(self, text):
        """Never drop output: fall back to the real stream, else to the log file."""
        if self.fallback:
            try:
                self.fallback.write(text)
                return
            except Exception:
                pass
        stripped = text.rstrip()
        if stripped:
            LOGGER.info(stripped)

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
                self._write_fallback(text)
        else:
            self._write_fallback(text)

    def flush(self):
        if self.fallback:
            try:
                self.fallback.flush()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Task Item Model for Parallel Execution
# ---------------------------------------------------------------------------
class KeywordTask:
    """Represents a single keyword task card and its associated background worker."""

    def __init__(self, task_id, keyword, limit=10, folder=""):
        self.task_id = task_id
        self.keyword_var = tk.StringVar(value=keyword)
        self.limit_var = tk.StringVar(value=str(limit))
        self.folder_var = tk.StringVar(value=folder)
        self.status_var = tk.StringVar(value="SIAP")
        self.status_type = "ready"  # ready, searching, downloading, success, stopped, error

        # Concurrency primitives
        self.thread = None
        self.stop_event = threading.Event()
        self.log_queue = queue.Queue()

        # UI Element References
        self.card_frame = None
        self.badge_label = None
        self.progress_bar = None
        self.progress_label = None
        self.btn_start = None
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
        self.geometry("1020x900")
        self.minsize(860, 740)

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

        # Click-through helper: ensure window takes key focus on first click.
        # A binding on the Toplevel fires for clicks on EVERY descendant, so it
        # must not steal focus from widgets that accept keyboard input.
        self.bind("<Button-1>", self._on_root_click, add=True)

        self._build_ui()
        self._seed_sample_tasks()
        self._poll_log_queues()

    def _on_root_click(self, event=None):
        widget = getattr(event, "widget", None)
        if isinstance(widget, (tk.Entry, tk.Text, ctk.CTkEntry, ctk.CTkTextbox)):
            return
        self.focus_set()

    def report_callback_exception(self, exc, val, tb):
        """Surface errors raised inside Tk callbacks.

        Tk routes these to sys.stderr, which a windowed .app bundle discards.
        Without this, an exception in a button's command is invisible and the
        button just appears unresponsive.
        """
        LOGGER.error("UI callback error:\n%s", "".join(traceback.format_exception(exc, val, tb)))
        try:
            messagebox.showerror(
                "Terjadi Kesalahan",
                f"{val}\n\nDetail lengkap tersimpan di:\n{LOG_PATH}",
            )
        except Exception:
            pass

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
        self.main_container.pack(fill="both", expand=True, padx=18, pady=14)

        # 1. Header Area with Astronaut Mascot Logo
        self._build_header(self.main_container)

        # 2. Main Tabview (Pencarian Kata Kunci, Tautan Tunggal, Berkas URL, Riset Solcoat)
        self._build_tabs(self.main_container)

        # 3. Settings Card (Delay Range & Default Folder)
        self._build_settings_card(self.main_container)

        # 4. Action Bar (Start All, Stop All, Open Base Folder, Progress Bar)
        self._build_action_bar(self.main_container)

        # 5. Dedicated Multi-Tab Console Card
        self._build_console_card(self.main_container)

    def _build_header(self, parent):
        header_frame = ctk.CTkFrame(parent, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 10))

        # Left Box: Logo & Titles
        left_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        left_box.pack(side="left", fill="y")

        base_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(base_dir, "assets", "logo.png")
        if os.path.exists(logo_path):
            try:
                pil_logo = Image.open(logo_path)
                self.logo_image = ctk.CTkImage(light_image=pil_logo, dark_image=pil_logo, size=(54, 54))
                logo_label = ctk.CTkLabel(left_box, image=self.logo_image, text="")
                logo_label.pack(side="left", padx=(0, 12))
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
            text="Scribd Bulk Search & Downloader — Eksekusi Bersamaan (Paralel)",
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
        self.tabview = ctk.CTkTabview(parent, height=320, corner_radius=10)
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

        # Tab 4: Research report from downloaded PDFs (text layer + OCR, no AI)
        self.tab_research = self.tabview.add(RESEARCH_TAB_NAME)
        self.research_panel = ResearchPanel(self, self.tab_research, FONT_FAMILY_MAIN)

    def _build_search_tab(self, tab):
        # Top Controls Bar
        ctrl_bar = ctk.CTkFrame(tab, fg_color="transparent")
        ctrl_bar.pack(fill="x", pady=(0, 6))

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
            height=190,
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
        card.pack(fill="x", pady=(0, 8), padx=2, ipady=3)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=8)

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
        ).pack(side="left", padx=(8, 16))

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
        action_row.pack(fill="x", pady=(0, 8))

        # Start All Button (Big Prominent)
        self.btn_start_all = ctk.CTkButton(
            action_row,
            text="Mulai Semua Bersamaan",
            font=(FONT_FAMILY_MAIN, 12, "bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            height=38,
            width=200,
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
    # Task Management & Dynamic UI Cards with Live Progress
    # ---------------------------------------------------------------------------
    def _seed_sample_tasks(self):
        sample_kws = ["Petrokimia Gresik", "Pupuk Kaltim", "Pupuk Indonesia"]
        for kw in sample_kws:
            self._create_task(kw, limit=10)
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
        self._create_task(f"Kata Kunci {idx}", limit=10)
        self._sync_task_summary()

    def _create_task(self, keyword, limit=10, folder=""):
        self.task_counter += 1
        task_id = f"task_{self.task_counter}"

        # Default folder if none provided
        if not folder:
            clean_slug = re.sub(r"[^\w\-]", "_", keyword.strip()).strip("_") or f"task_{self.task_counter}"
            folder = os.path.join(self._get_base_folder(), clean_slug)

        task = KeywordTask(task_id, keyword, limit, folder)

        # Build Rich Card Widget in tasks_scroll
        card = ctk.CTkFrame(
            self.tasks_scroll,
            corner_radius=8,
            fg_color="#1e293b",
            border_width=1,
            border_color="#334155",
        )
        card.pack(fill="x", pady=4, padx=2)
        task.card_frame = card

        # Line 1: Keyword, Target, Status Badge, Individual Start / Stop / Remove Buttons
        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", padx=10, pady=(6, 2))

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
            width=220,
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
        ).pack(side="left", padx=(0, 10))

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

        # Action Buttons on Right: Remove, Stop, Start
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

        btn_start_single = ctk.CTkButton(
            row1,
            text="Mulai",
            width=60,
            height=26,
            font=(FONT_FAMILY_MAIN, 10, "bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=lambda t=task: self._start_single_task(t),
        )
        btn_start_single.pack(side="right", padx=(0, 6))
        task.btn_start = btn_start_single

        # Line 2: Live Progress Bar & Status Text for this Keyword
        row_prog = ctk.CTkFrame(card, fg_color="transparent")
        row_prog.pack(fill="x", padx=10, pady=(2, 4))

        prog_bar = ctk.CTkProgressBar(
            row_prog,
            height=8,
            corner_radius=4,
            progress_color="#3b82f6",
        )
        prog_bar.pack(side="left", fill="x", expand=True, padx=(34, 10))
        prog_bar.set(0)
        task.progress_bar = prog_bar

        lbl_prog = ctk.CTkLabel(
            row_prog,
            text="Menunggu...",
            font=(FONT_FAMILY_MAIN, 10),
            text_color="#94a3b8",
            width=180,
            anchor="w",
        )
        lbl_prog.pack(side="right")
        task.progress_label = lbl_prog

        # Line 3: Destination Folder & Browse Button
        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=10, pady=(0, 6))

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
                text=f"{running} Berjalan Bersamaan, {total - running} Siap/Selesai",
                text_color="#f59e0b",
            )
        else:
            self.lbl_task_summary.configure(
                text=f"{total} Tugas Siap Dijalankan",
                text_color="#60a5fa",
            )

    def _ensure_console_tab_for_task(self, task):
        kw = task.keyword_var.get().strip() or f"Tugas {task.task_id}"
        clean_name = kw[:24].strip()

        if task.tab_name == clean_name and clean_name in self.active_console_tabs:
            return

        if task.tab_name and task.tab_name != clean_name and task.tab_name in self.active_console_tabs:
            try:
                self.console_tabview.delete(task.tab_name)
            except Exception:
                pass
            self.active_console_tabs.pop(task.tab_name, None)

        if clean_name not in self.active_console_tabs:
            try:
                tab_frame = self.console_tabview.add(clean_name)
            except Exception:
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
                    self._create_task(line, limit=10)
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
        try:
            os.makedirs(p, exist_ok=True)
        except OSError as exc:
            # macOS guards ~/Downloads and ~/Documents behind TCC. A bundled app
            # that has not been granted access raises here, and every action
            # button routes through this method -- so swallowing it would make
            # the whole UI look dead.
            LOGGER.error("Cannot create output folder %s: %s", p, exc)
            messagebox.showerror(
                "Folder Tidak Dapat Dibuat",
                f"Tidak bisa membuat atau mengakses folder:\n{p}\n\n{exc}\n\n"
                "Beri izin akses folder di System Settings > Privacy & Security > Files and Folders, "
                "atau pilih folder lain lewat tombol Pilih Folder.",
            )
            raise
        return p

    def _browse_base_folder(self):
        self.update_idletasks()
        cur = self._get_base_folder()
        d = filedialog.askdirectory(parent=self, title="Pilih Folder Penyimpanan Utama", initialdir=cur)
        if d:
            self.base_folder_var.set(d)

    def _browse_custom_folder(self, string_var):
        self.update_idletasks()
        cur = string_var.get().strip() or self._get_base_folder()
        d = filedialog.askdirectory(parent=self, title="Pilih Folder Simpan Dokumen", initialdir=cur)
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
        self.update_idletasks()
        f = filedialog.askopenfilename(
            parent=self,
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

        self.research_panel.poll()

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
    def _any_download_running(self):
        """Unduhan saja. Riset Solcoat sengaja tidak dihitung agar unduhan tetap bisa dimulai saat riset berjalan."""
        if self.solo_thread and self.solo_thread.is_alive():
            return True
        return any(t.thread and t.thread.is_alive() for t in self.tasks)

    def _any_task_running(self):
        return self._any_download_running() or self.research_panel.is_running()

    def _update_global_ui_state(self):
        running = self._any_task_running()
        downloading = self._any_download_running()
        researching = self.research_panel.is_running()
        if running:
            if downloading:
                self.btn_start_all.configure(state="disabled", fg_color="#475569")
            else:
                self.btn_start_all.configure(state="normal", fg_color="#2563eb")
            self.btn_stop_all.configure(state="normal", fg_color="#dc2626", text="Hentikan Semua")
            self.progress_bar.start()

            active_count = sum(1 for t in self.tasks if t.thread and t.thread.is_alive())
            if active_count > 0:
                badge = f"{active_count} BERJALAN BERSAMAAN" + (" + RISET" if researching else "")
            elif downloading:
                badge = "BERJALAN" + (" + RISET" if researching else "")
            else:
                badge = "RISET BERJALAN"
            self.global_status_badge.configure(text=badge, text_color="#f59e0b", fg_color="#78350f")
        else:
            self.btn_start_all.configure(state="normal", fg_color="#2563eb")
            self.btn_stop_all.configure(state="disabled", fg_color="#475569", text="Hentikan Semua")
            self.progress_bar.stop()
            self.progress_bar.set(0)

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
        self.update_idletasks()

    def _set_task_status(self, task, text, badge_type="ready", progress_val=None, progress_info=None):
        task.status_var.set(text)
        task.status_type = badge_type

        badge_configs = {
            "ready": ("#10b981", "#064e3b"),
            "searching": ("#f59e0b", "#78350f"),
            "downloading": ("#38bdf8", "#0c4a6e"),
            "stopped": ("#ef4444", "#7f1d1d"),
            "success": ("#34d399", "#065f46"),
            "error": ("#ef4444", "#7f1d1d"),
        }
        fg_col, bg_col = badge_configs.get(badge_type, ("#10b981", "#064e3b"))
        if task.badge_label:
            task.badge_label.configure(text=text, text_color=fg_col, fg_color=bg_col)

        if task.progress_bar:
            if progress_val is not None:
                task.progress_bar.set(progress_val)
            elif badge_type == "searching":
                task.progress_bar.configure(mode="indeterminate")
                task.progress_bar.start()
            elif badge_type == "success":
                task.progress_bar.stop()
                task.progress_bar.configure(mode="determinate")
                task.progress_bar.set(1.0)
            elif badge_type in ("stopped", "error", "ready"):
                task.progress_bar.stop()
                task.progress_bar.configure(mode="determinate")
                if badge_type == "ready":
                    task.progress_bar.set(0)

        if task.progress_label and progress_info:
            task.progress_label.configure(text=progress_info)

        if badge_type in ("searching", "downloading"):
            if task.btn_start:
                task.btn_start.configure(state="disabled", fg_color="#475569")
            if task.btn_stop:
                task.btn_stop.configure(state="normal", fg_color="#dc2626")
            if task.btn_remove:
                task.btn_remove.configure(state="disabled")
        else:
            if task.btn_start:
                task.btn_start.configure(state="normal", fg_color="#2563eb")
            if task.btn_stop:
                task.btn_stop.configure(state="disabled", fg_color="#475569")
            if task.btn_remove:
                task.btn_remove.configure(state="normal")

        self.update_idletasks()

    def _start_single_task(self, task):
        """Starts an individual keyword task."""
        if task.thread and task.thread.is_alive():
            return

        kw = task.keyword_var.get().strip()
        if not kw:
            messagebox.showwarning("Peringatan", "Kata kunci tidak boleh kosong.")
            return

        try:
            min_delay = max(0.5, float(self.min_delay_var.get().strip()))
            max_delay = max(min_delay, float(self.max_delay_var.get().strip()))
        except Exception:
            min_delay = 1.0
            max_delay = 5.0

        try:
            limit = max(1, int(task.limit_var.get().strip()))
        except Exception:
            limit = 10
            task.limit_var.set("10")

        out_dir = task.folder_var.get().strip()
        if not out_dir:
            clean_slug = re.sub(r"[^\w\-]", "_", kw).strip("_")
            out_dir = os.path.join(self._get_base_folder(), clean_slug)
            task.folder_var.set(out_dir)

        self._ensure_console_tab_for_task(task)
        task.stop_event.clear()
        if task.btn_stop:
            task.btn_stop.configure(text="Hentikan")

        self._set_task_status(task, "MENCARI...", badge_type="searching", progress_info="Sedang mencari dokumen di Scribd...")

        t = threading.Thread(
            target=self._parallel_keyword_worker,
            args=(task, limit, out_dir, min_delay, max_delay),
            daemon=True,
        )
        task.thread = t
        t.start()

        if task.tab_name:
            try:
                self.console_tabview.set(task.tab_name)
            except Exception:
                pass

        self._update_global_ui_state()

    def _stop_single_task(self, task):
        if task.thread and task.thread.is_alive():
            task.stop_event.set()
            task.log_queue.put("\n[STOP] Sinyal henti dikirim untuk tugas ini...\n")
            if task.btn_stop:
                task.btn_stop.configure(state="disabled", text="MENGHENTIKAN")
            self._set_task_status(task, "MENGHENTIKAN", badge_type="stopped", progress_info="Menghentikan proses...")

    def _stop_all_processes(self):
        for task in self.tasks:
            if task.thread and task.thread.is_alive():
                task.stop_event.set()
                task.log_queue.put("\n[STOP] Sinyal henti global dikirim untuk tugas ini...\n")
                if task.btn_stop:
                    task.btn_stop.configure(state="disabled")

        if self.solo_thread and self.solo_thread.is_alive():
            self.solo_stop_event.set()
            self.solo_queue.put("\n[STOP] Sinyal henti dikirim...\n")

        self.research_panel.stop()

        self.btn_stop_all.configure(state="disabled", text="MENGHENTIKAN...")
        self.update_idletasks()

    def _start_all_processes(self):
        """Starts ALL valid keyword tasks simultaneously in parallel threads."""
        self.update_idletasks()
        active_tab_mode = self.tabview.get()
        if active_tab_mode != RESEARCH_TAB_NAME and self._any_download_running():
            return

        if active_tab_mode == RESEARCH_TAB_NAME:
            self.research_panel.start()
            return

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

            # Launch all tasks simultaneously in separate threads at t=0
            for task in valid_tasks:
                self._ensure_console_tab_for_task(task)
                task.stop_event.clear()
                if task.btn_stop:
                    task.btn_stop.configure(text="Hentikan")

                try:
                    limit = max(1, int(task.limit_var.get().strip()))
                except Exception:
                    limit = 10
                    task.limit_var.set("10")

                out_dir = task.folder_var.get().strip()
                if not out_dir:
                    clean_slug = re.sub(r"[^\w\-]", "_", task.keyword_var.get().strip()).strip("_")
                    out_dir = os.path.join(self._get_base_folder(), clean_slug)
                    task.folder_var.set(out_dir)

                self._set_task_status(
                    task,
                    "MENCARI...",
                    badge_type="searching",
                    progress_info=f"Sedang mencari {limit} dokumen...",
                )

                # Launch concurrent worker thread
                t = threading.Thread(
                    target=self._parallel_keyword_worker,
                    args=(task, limit, out_dir, min_delay, max_delay),
                    daemon=True,
                )
                task.thread = t
                t.start()

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
        self.stdout_router.register(tid, task.log_queue)

        kw = task.keyword_var.get().strip()

        def status_cb(stage, details):
            if stage == "MENCARI":
                self.after(
                    0,
                    lambda: self._set_task_status(
                        task,
                        "MENCARI...",
                        badge_type="searching",
                        progress_info="Mencari dokumen di Scribd...",
                    ),
                )
            elif stage == "MENGUNDUH":
                cur = details.get("current", 0)
                tot = details.get("total", limit)
                succ = details.get("success", 0)
                fraction = (cur / tot) if tot > 0 else 0.0
                info_txt = f"Mengunduh {cur}/{tot} (Sukses: {succ})"
                badge_lbl = f"UNDUH ({cur}/{tot})"
                self.after(
                    0,
                    lambda: self._set_task_status(
                        task,
                        badge_lbl,
                        badge_type="downloading",
                        progress_val=fraction,
                        progress_info=info_txt,
                    ),
                )
            elif stage == "SELESAI":
                succ = details.get("success", 0) if isinstance(details, dict) else 0
                self.after(
                    0,
                    lambda: self._set_task_status(
                        task,
                        "SELESAI",
                        badge_type="success",
                        progress_val=1.0,
                        progress_info=f"Selesai! {succ} PDF tersimpan",
                    ),
                )
            elif stage == "DIHENTIKAN":
                self.after(
                    0,
                    lambda: self._set_task_status(
                        task,
                        "DIHENTIKAN",
                        badge_type="stopped",
                        progress_info="Tugas dihentikan oleh pengguna.",
                    ),
                )

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
            succ = stats.get("success", 0)
            msg = "Dihentikan oleh pengguna." if badge_type == "stopped" else f"Selesai! {succ} PDF tersimpan"
            self.after(
                0,
                lambda: self._set_task_status(
                    task,
                    status_text,
                    badge_type=badge_type,
                    progress_val=1.0 if badge_type == "success" else None,
                    progress_info=msg,
                ),
            )

        except Exception as exc:
            task.log_queue.put(f"\n[ERROR] Terjadi kesalahan pada tugas '{kw}': {exc}\n")
            self.after(
                0,
                lambda: self._set_task_status(
                    task,
                    "ERROR",
                    badge_type="error",
                    progress_info=f"Kesalahan: {exc}",
                ),
            )
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
    # The research scan uses a process pool; frozen .app/.exe builds re-launch this
    # executable for each worker, and freeze_support() routes those launches.
    multiprocessing.freeze_support()
    main()
