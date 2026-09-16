#!/usr/bin/env python3
"""
Momo Rescribd — Modern GUI for Scribd Bulk Search & Downloader.
Cross-platform desktop app for macOS, Windows, and Linux.
Features:
- Multi-keyword queue search & automated bulk download
- Real-time Stop / Cancellation with instant browser cleanup
- Dynamic random delay range (1000 - 5000 ms) to avoid rate limits
- Modern, clean, and elegant card-based UI/UX
- Ready for compilation to macOS .app / .dmg and Windows .exe
"""

import os
import queue
import random
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import scribd_engine as engine


# ---------------------------------------------------------------------------
# Cross-Platform Helpers & Fonts
# ---------------------------------------------------------------------------
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

if IS_WINDOWS:
    FONT_FAMILY_MAIN = "Segoe UI"
    FONT_FAMILY_MONO = "Consolas"
elif IS_MAC:
    FONT_FAMILY_MAIN = "SF Pro Text"
    FONT_FAMILY_MONO = "Menlo"
else:
    FONT_FAMILY_MAIN = "Ubuntu"
    FONT_FAMILY_MONO = "Monospace"


class QueueWriter:
    """Redirects stdout and stderr to a thread-safe queue for the GUI."""

    def __init__(self, log_queue):
        self.queue = log_queue

    def write(self, text):
        if text:
            self.queue.put(text)

    def flush(self):
        pass


# ---------------------------------------------------------------------------
# Main Application Class
# ---------------------------------------------------------------------------
class MomoRescribdApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Momo Rescribd — Scribd Bulk Search & Downloader")
        self.geometry("860x780")
        self.minsize(760, 680)

        # Set Window Icon (cross-platform)
        self._set_app_icon()

        # State Variables
        self.output_dir_var = tk.StringVar(value="")
        self.single_url_var = tk.StringVar(value="")
        self.file_path_var = tk.StringVar(value="")
        self.limit_var = tk.IntVar(value=5)
        self.min_delay_var = tk.DoubleVar(value=1.0)
        self.max_delay_var = tk.DoubleVar(value=5.0)

        self.is_running = False
        self.worker_thread = None
        self.stop_event = threading.Event()
        self.log_queue = queue.Queue()

        self._configure_theme()
        self._build_ui()
        self._poll_log_queue()

    def _set_app_icon(self):
        """Set application icon for Windows and macOS/Linux."""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        ico_path = os.path.join(base_dir, "assets", "momo_rescribd.ico")
        if IS_WINDOWS and os.path.exists(ico_path):
            try:
                self.iconbitmap(ico_path)
            except Exception:
                pass

    def _configure_theme(self):
        """Apply modern, elegant color palette and widget styling."""
        self.style = ttk.Style(self)

        # Base color tokens
        self.COLOR_BG = "#f8fafc"         # Slate-50
        self.COLOR_CARD = "#ffffff"       # White
        self.COLOR_BORDER = "#e2e8f0"     # Slate-200
        self.COLOR_TEXT = "#0f172a"       # Slate-900
        self.COLOR_SUBTEXT = "#64748b"    # Slate-500
        self.COLOR_PRIMARY = "#4f46e5"    # Indigo-600
        self.COLOR_DANGER = "#ef4444"     # Red-500

        self.configure(bg=self.COLOR_BG)

        try:
            if IS_MAC:
                self.style.theme_use("aqua")
            elif "clam" in self.style.theme_names():
                self.style.theme_use("clam")
        except Exception:
            pass

        # Configure custom TTK styles
        self.style.configure(".", font=(FONT_FAMILY_MAIN, 11), background=self.COLOR_BG)
        self.style.configure("TFrame", background=self.COLOR_BG)

        # Card frames
        self.style.configure(
            "Card.TFrame",
            background=self.COLOR_CARD,
            relief="solid",
            borderwidth=1,
        )

        # Typography
        self.style.configure(
            "AppTitle.TLabel",
            font=(FONT_FAMILY_MAIN, 18, "bold"),
            foreground=self.COLOR_TEXT,
            background=self.COLOR_BG,
        )
        self.style.configure(
            "AppSubtitle.TLabel",
            font=(FONT_FAMILY_MAIN, 11),
            foreground=self.COLOR_SUBTEXT,
            background=self.COLOR_BG,
        )
        self.style.configure(
            "CardTitle.TLabel",
            font=(FONT_FAMILY_MAIN, 12, "bold"),
            foreground=self.COLOR_TEXT,
            background=self.COLOR_CARD,
        )
        self.style.configure(
            "CardSubtitle.TLabel",
            font=(FONT_FAMILY_MAIN, 10),
            foreground=self.COLOR_SUBTEXT,
            background=self.COLOR_CARD,
        )
        self.style.configure(
            "Muted.TLabel",
            font=(FONT_FAMILY_MAIN, 10),
            foreground=self.COLOR_SUBTEXT,
            background=self.COLOR_CARD,
        )

        # Tabs styling
        self.style.configure(
            "TNotebook",
            background=self.COLOR_BG,
            borderwidth=0,
        )
        self.style.configure(
            "TNotebook.Tab",
            font=(FONT_FAMILY_MAIN, 11, "bold"),
            padding=(14, 6),
        )

        # Buttons
        self.style.configure(
            "Primary.TButton",
            font=(FONT_FAMILY_MAIN, 12, "bold"),
            padding=(16, 8),
        )
        self.style.configure(
            "Danger.TButton",
            font=(FONT_FAMILY_MAIN, 12, "bold"),
            padding=(14, 8),
        )
        self.style.configure(
            "Secondary.TButton",
            font=(FONT_FAMILY_MAIN, 11),
            padding=(10, 6),
        )

    # ---------------------------------------------------------------------------
    # UI Layout Construction
    # ---------------------------------------------------------------------------
    def _build_ui(self):
        container = ttk.Frame(self, padding="20 16 20 16")
        container.pack(fill=tk.BOTH, expand=True)

        # 1. Header Area (Branding & Status Pill)
        header_frame = ttk.Frame(container)
        header_frame.pack(fill=tk.X, pady=(0, 14))

        left_header = ttk.Frame(header_frame)
        left_header.pack(side=tk.LEFT, fill=tk.Y)

        title_label = ttk.Label(left_header, text="📚 Momo Rescribd", style="AppTitle.TLabel")
        title_label.pack(anchor=tk.W)

        subtitle_label = ttk.Label(
            left_header,
            text="Scribd Bulk Search & Downloader — Multi-Keyword, PDF Bersih, & Bebas Deteksi Bot",
            style="AppSubtitle.TLabel",
        )
        subtitle_label.pack(anchor=tk.W, pady=(2, 0))

        right_header = ttk.Frame(header_frame)
        right_header.pack(side=tk.RIGHT, fill=tk.Y)

        # Status Pill Badge
        self.status_badge = tk.Label(
            right_header,
            text="● Siap Digunakan",
            font=(FONT_FAMILY_MAIN, 11, "bold"),
            bg="#ecfdf5",
            fg="#047857",
            padx=12,
            pady=4,
            relief="solid",
            bd=1,
        )
        self.status_badge.pack(anchor=tk.E, pady=(2, 0))

        # 2. Mode Selector / Tabs Area
        self.notebook = ttk.Notebook(container)
        self.notebook.pack(fill=tk.X, pady=(0, 10))

        # --- Tab 1: Multi-Keyword Search ---
        self.tab_search = ttk.Frame(self.notebook, padding="14 12 14 12")
        self.notebook.add(self.tab_search, text="  🔍 Multi Pencarian Kata Kunci  ")
        self._build_tab_search()

        # --- Tab 2: Single Document ---
        self.tab_single = ttk.Frame(self.notebook, padding="14 12 14 12")
        self.notebook.add(self.tab_single, text="  🔗 Unduh 1 Link Scribd  ")
        self._build_tab_single()

        # --- Tab 3: File of URLs ---
        self.tab_file = ttk.Frame(self.notebook, padding="14 12 14 12")
        self.notebook.add(self.tab_file, text="  📄 Unduh dari File Teks (urls.txt)  ")
        self._build_tab_file()

        # 3. Settings Card (Random Delay & Output Directory)
        self._build_settings_card(container)

        # 4. Action & Progress Bar Area
        self._build_action_bar(container)

        # 5. Live Console Terminal Output
        self._build_terminal_console(container)

    def _build_tab_search(self):
        desc_lbl = ttk.Label(
            self.tab_search,
            text="Masukkan satu atau beberapa kata kunci pencarian. Sistem akan mencari dan mengunduh dokumen secara berurutan:",
            style="AppSubtitle.TLabel",
        )
        desc_lbl.pack(anchor=tk.W, pady=(0, 6))

        # Multi-line keywords textbox
        text_frame = tk.Frame(self.tab_search, bg=self.COLOR_CARD, relief="solid", bd=1)
        text_frame.pack(fill=tk.X, pady=(0, 6))

        self.keyword_text = tk.Text(
            text_frame,
            height=4,
            font=(FONT_FAMILY_MAIN, 11),
            wrap=tk.WORD,
            padx=8,
            pady=8,
            relief="flat",
        )
        self.keyword_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scroll_kw = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.keyword_text.yview)
        scroll_kw.pack(side=tk.RIGHT, fill=tk.Y)
        self.keyword_text.config(yscrollcommand=scroll_kw.set)

        # Quick placeholder text
        sample_prompt = "Petrokimia Gresik\nPupuk Kaltim\nPupuk Indonesia"
        self.keyword_text.insert(tk.END, sample_prompt)
        self.keyword_text.bind("<KeyRelease>", self._update_keyword_count)

        # Counter & limit options
        footer_row = ttk.Frame(self.tab_search)
        footer_row.pack(fill=tk.X, pady=(2, 0))

        self.kw_count_label = ttk.Label(
            footer_row,
            text="📌 3 kata kunci terdeteksi",
            font=(FONT_FAMILY_MAIN, 10, "bold"),
            foreground="#4338ca",
        )
        self.kw_count_label.pack(side=tk.LEFT)

        btn_sample = ttk.Button(
            footer_row,
            text="Reset Contoh",
            style="Secondary.TButton",
            command=self._reset_sample_keywords,
        )
        btn_sample.pack(side=tk.LEFT, padx=(10, 0))

        limit_frame = ttk.Frame(footer_row)
        limit_frame.pack(side=tk.RIGHT)

        ttk.Label(limit_frame, text="Target Dokumen per Kata Kunci:").pack(side=tk.LEFT, padx=(0, 6))
        limit_spin = ttk.Spinbox(
            limit_frame,
            from_=1,
            to=100,
            textvariable=self.limit_var,
            width=6,
            font=(FONT_FAMILY_MAIN, 11),
        )
        limit_spin.pack(side=tk.LEFT)

    def _build_tab_single(self):
        desc_lbl = ttk.Label(
            self.tab_single,
            text="Masukkan satu tautan dokumen Scribd spesifik untuk diunduh langsung sebagai file PDF:",
            style="AppSubtitle.TLabel",
        )
        desc_lbl.pack(anchor=tk.W, pady=(0, 8))

        row = ttk.Frame(self.tab_single)
        row.pack(fill=tk.X, pady=4)

        ttk.Label(row, text="Link URL:").pack(side=tk.LEFT, padx=(0, 8))
        self.entry_single_url = ttk.Entry(row, textvariable=self.single_url_var, font=(FONT_FAMILY_MAIN, 11))
        self.entry_single_url.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        btn_paste = ttk.Button(row, text="📋 Paste", style="Secondary.TButton", command=self._paste_single_url)
        btn_paste.pack(side=tk.RIGHT)

        hint = ttk.Label(
            self.tab_single,
            text="Contoh: https://www.scribd.com/document/320976464/Praktek-Kerja-Lapangan-PT-Pupuk-Kaltim",
            style="Muted.TLabel",
        )
        hint.pack(anchor=tk.W, pady=(4, 0))

    def _build_tab_file(self):
        desc_lbl = ttk.Label(
            self.tab_file,
            text="Pilih file teks (.txt) yang berisi daftar link dokumen Scribd (satu baris per tautan):",
            style="AppSubtitle.TLabel",
        )
        desc_lbl.pack(anchor=tk.W, pady=(0, 8))

        row = ttk.Frame(self.tab_file)
        row.pack(fill=tk.X, pady=4)

        ttk.Label(row, text="File Path:").pack(side=tk.LEFT, padx=(0, 8))
        entry_file = ttk.Entry(row, textvariable=self.file_path_var, font=(FONT_FAMILY_MAIN, 11))
        entry_file.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        btn_browse = ttk.Button(row, text="Pilih File...", style="Secondary.TButton", command=self._browse_file)
        btn_browse.pack(side=tk.RIGHT)

    def _build_settings_card(self, parent):
        card = tk.Frame(parent, bg=self.COLOR_CARD, relief="solid", bd=1, padx=14, pady=12)
        card.pack(fill=tk.X, pady=(0, 10))

        # Row 1: Random Delay Range
        delay_row = tk.Frame(card, bg=self.COLOR_CARD)
        delay_row.pack(fill=tk.X, pady=(0, 8))

        lbl_delay = tk.Label(
            delay_row,
            text="⏱️ Jeda Acak (Random Delay):",
            font=(FONT_FAMILY_MAIN, 11, "bold"),
            bg=self.COLOR_CARD,
            fg=self.COLOR_TEXT,
        )
        lbl_delay.pack(side=tk.LEFT, padx=(0, 10))

        spin_min = ttk.Spinbox(
            delay_row,
            from_=0.5,
            to=60.0,
            increment=0.5,
            textvariable=self.min_delay_var,
            width=5,
            font=(FONT_FAMILY_MAIN, 11),
        )
        spin_min.pack(side=tk.LEFT)

        tk.Label(delay_row, text="detik  s/d", bg=self.COLOR_CARD, fg=self.COLOR_SUBTEXT).pack(side=tk.LEFT, padx=6)

        spin_max = ttk.Spinbox(
            delay_row,
            from_=1.0,
            to=120.0,
            increment=0.5,
            textvariable=self.max_delay_var,
            width=5,
            font=(FONT_FAMILY_MAIN, 11),
        )
        spin_max.pack(side=tk.LEFT)

        tk.Label(delay_row, text="detik", bg=self.COLOR_CARD, fg=self.COLOR_SUBTEXT).pack(side=tk.LEFT, padx=(6, 12))

        sub_delay = tk.Label(
            delay_row,
            text="(Jeda otomatis diacak antara 1000 - 5000 ms agar bebas blokir)",
            font=(FONT_FAMILY_MAIN, 10),
            bg=self.COLOR_CARD,
            fg=self.COLOR_SUBTEXT,
        )
        sub_delay.pack(side=tk.LEFT)

        # Row 2: Storage Folder
        folder_row = tk.Frame(card, bg=self.COLOR_CARD)
        folder_row.pack(fill=tk.X)

        lbl_folder = tk.Label(
            folder_row,
            text="📁 Folder Simpan PDF:",
            font=(FONT_FAMILY_MAIN, 11, "bold"),
            bg=self.COLOR_CARD,
            fg=self.COLOR_TEXT,
        )
        lbl_folder.pack(side=tk.LEFT, padx=(0, 10))

        self.entry_folder = ttk.Entry(folder_row, textvariable=self.output_dir_var, font=(FONT_FAMILY_MAIN, 11))
        self.entry_folder.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        btn_folder = ttk.Button(folder_row, text="Pilih Folder...", style="Secondary.TButton", command=self._browse_folder)
        btn_folder.pack(side=tk.RIGHT)

        hint_folder = tk.Label(
            card,
            text="💡 Kosongkan untuk otomatis menyimpan ke folder Downloads/Momo_Rescribd (aman & tidak mengekspos username)",
            font=(FONT_FAMILY_MAIN, 10),
            bg=self.COLOR_CARD,
            fg=self.COLOR_SUBTEXT,
        )
        hint_folder.pack(anchor=tk.W, pady=(4, 0))

    def _build_action_bar(self, parent):
        action_card = ttk.Frame(parent)
        action_card.pack(fill=tk.X, pady=(0, 10))

        # Action Buttons
        self.btn_start = tk.Button(
            action_card,
            text="🚀 Mulai Download",
            font=(FONT_FAMILY_MAIN, 12, "bold"),
            bg="#4f46e5",
            fg="#ffffff",
            activebackground="#4338ca",
            activeforeground="#ffffff",
            padx=18,
            pady=8,
            relief="flat",
            cursor="hand2",
            command=self._start_process,
        )
        self.btn_start.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_stop = tk.Button(
            action_card,
            text="🛑 Berhenti (Stop)",
            font=(FONT_FAMILY_MAIN, 12, "bold"),
            bg="#ef4444",
            fg="#ffffff",
            activebackground="#dc2626",
            activeforeground="#ffffff",
            padx=16,
            pady=8,
            relief="flat",
            state=tk.DISABLED,
            cursor="hand2",
            command=self._stop_process,
        )
        self.btn_stop.pack(side=tk.LEFT, padx=(0, 10))

        self.btn_open_folder = tk.Button(
            action_card,
            text="📂 Buka Folder Hasil",
            font=(FONT_FAMILY_MAIN, 11),
            bg="#f1f5f9",
            fg="#1e293b",
            activebackground="#e2e8f0",
            activeforeground="#0f172a",
            padx=14,
            pady=8,
            relief="solid",
            bd=1,
            cursor="hand2",
            command=self._open_output_folder,
        )
        self.btn_open_folder.pack(side=tk.LEFT)

        # Progress bar
        self.progress = ttk.Progressbar(action_card, mode="indeterminate", length=180)
        self.progress.pack(side=tk.RIGHT, padx=(10, 0))

    def _build_terminal_console(self, parent):
        term_frame = tk.Frame(parent, bg="#0f172a", relief="solid", bd=1)
        term_frame.pack(fill=tk.BOTH, expand=True)

        # Terminal Header Bar
        top_bar = tk.Frame(term_frame, bg="#1e293b", padx=10, pady=6)
        top_bar.pack(fill=tk.X)

        tk.Label(
            top_bar,
            text="💻 Console Log & Status Progres",
            font=(FONT_FAMILY_MAIN, 10, "bold"),
            bg="#1e293b",
            fg="#94a3b8",
        ).pack(side=tk.LEFT)

        btn_copy = tk.Button(
            top_bar,
            text="📋 Salin Log",
            font=(FONT_FAMILY_MAIN, 9),
            bg="#334155",
            fg="#f8fafc",
            activebackground="#475569",
            activeforeground="#ffffff",
            padx=8,
            pady=2,
            relief="flat",
            command=self._copy_log,
        )
        btn_copy.pack(side=tk.RIGHT, padx=(6, 0))

        btn_clear = tk.Button(
            top_bar,
            text="🗑️ Bersihkan",
            font=(FONT_FAMILY_MAIN, 9),
            bg="#334155",
            fg="#f8fafc",
            activebackground="#475569",
            activeforeground="#ffffff",
            padx=8,
            pady=2,
            relief="flat",
            command=self._clear_log,
        )
        btn_clear.pack(side=tk.RIGHT)

        # Scrolled Text Terminal
        self.log_text = ScrolledText(
            term_frame,
            wrap=tk.WORD,
            font=(FONT_FAMILY_MONO, 10),
            background="#0f172a",
            foreground="#f8fafc",
            insertbackground="#38bdf8",
            selectbackground="#334155",
            padx=10,
            pady=8,
            relief="flat",
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

    # ---------------------------------------------------------------------------
    # UI State & Badge Management
    # ---------------------------------------------------------------------------
    def _set_ui_state(self, running, status_text="Siap", badge_type="ready"):
        self.is_running = running

        if running:
            self.btn_start.config(state=tk.DISABLED, bg="#94a3b8")
            self.btn_stop.config(state=tk.NORMAL, bg="#ef4444")
            self.progress.start(10)
        else:
            self.btn_start.config(state=tk.NORMAL, bg="#4f46e5")
            self.btn_stop.config(state=tk.DISABLED, bg="#94a3b8")
            self.progress.stop()

        # Update status badge
        badge_colors = {
            "ready": ("#ecfdf5", "#047857"),       # Emerald
            "running": ("#fffbeb", "#b45309"),     # Amber
            "stopped": ("#fef2f2", "#b91c1c"),     # Red
            "success": ("#eff6ff", "#1d4ed8"),     # Blue
        }
        bg_col, fg_col = badge_colors.get(badge_type, ("#ecfdf5", "#047857"))
        self.status_badge.config(text=f"● {status_text}", bg=bg_col, fg=fg_col)

    def _update_keyword_count(self, event=None):
        raw = self.keyword_text.get("1.0", tk.END).strip()
        keywords = self._parse_keywords(raw)
        count = len(keywords)
        if count == 0:
            self.kw_count_label.config(text="⚠️ Belum ada kata kunci", foreground="#dc2626")
        elif count == 1:
            self.kw_count_label.config(text="📌 1 kata kunci terdeteksi", foreground="#4338ca")
        else:
            self.kw_count_label.config(text=f"📌 {count} kata kunci terdeteksi", foreground="#4338ca")

    def _parse_keywords(self, raw_text):
        if not raw_text:
            return []
        tokens = raw_text.replace("\n", ",").split(",")
        return [t.strip() for t in tokens if t.strip()]

    def _reset_sample_keywords(self):
        self.keyword_text.delete("1.0", tk.END)
        self.keyword_text.insert(tk.END, "Petrokimia Gresik\nPupuk Kaltim\nPupuk Indonesia")
        self._update_keyword_count()

    def _paste_single_url(self):
        try:
            clipboard = self.clipboard_get()
            self.single_url_var.set(clipboard.strip())
        except Exception:
            pass

    def _browse_file(self):
        f = filedialog.askopenfilename(
            title="Pilih File Teks Daftar URL",
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

    def _display_path(self, path):
        return engine.display_path(path)

    def _open_output_folder(self):
        folder = self._get_effective_output_dir()
        if not engine.open_in_file_manager(folder):
            messagebox.showinfo("Informasi", f"Folder belum ada atau gagal dibuka:\n{self._display_path(folder)}")

    def _clear_log(self):
        self.log_text.delete("1.0", tk.END)

    def _copy_log(self):
        text = self.log_text.get("1.0", tk.END)
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("Sukses", "Seluruh log berhasil disalin ke clipboard!")

    def _poll_log_queue(self):
        while not self.log_queue.empty():
            try:
                msg = self.log_queue.get_nowait()
                self.log_text.insert(tk.END, msg)
                self.log_text.see(tk.END)
            except queue.Empty:
                break
        self.after(100, self._poll_log_queue)

    def _log(self, text):
        self.log_queue.put(text + "\n")

    # ---------------------------------------------------------------------------
    # Action Execution & Stop Logic
    # ---------------------------------------------------------------------------
    def _stop_process(self):
        """Signals background worker thread to abort immediately."""
        if not self.is_running:
            return

        self._log("\n🛑 Mengirim sinyal berhenti... Menutup browser dan proses...")
        self.stop_event.set()
        self.btn_stop.config(state=tk.DISABLED, text="🛑 Menghentikan...")
        self.status_badge.config(text="● Menghentikan...", bg="#fef2f2", fg="#b91c1c")

    def _start_process(self):
        if self.is_running:
            return

        current_tab = self.notebook.index(self.notebook.select())
        out_dir = self._get_effective_output_dir()

        min_delay = max(0.5, float(self.min_delay_var.get()))
        max_delay = max(min_delay, float(self.max_delay_var.get()))

        self.stop_event.clear()

        # Tab 0: Multi-Keyword Search
        if current_tab == 0:
            raw_kw = self.keyword_text.get("1.0", tk.END).strip()
            keywords = self._parse_keywords(raw_kw)
            if not keywords:
                messagebox.showwarning("Peringatan", "Silakan masukkan minimal satu kata kunci pencarian.")
                return

            limit = max(1, int(self.limit_var.get()))
            self._set_ui_state(True, status_text="Mencari & Mengunduh...", badge_type="running")
            self.btn_stop.config(text="🛑 Berhenti (Stop)")

            self.worker_thread = threading.Thread(
                target=self._run_multi_search_worker,
                args=(keywords, limit, out_dir, min_delay, max_delay),
                daemon=True,
            )
            self.worker_thread.start()

        # Tab 1: Single URL
        elif current_tab == 1:
            url = self.single_url_var.get().strip()
            if not url:
                messagebox.showwarning("Peringatan", "Silakan masukkan link dokumen Scribd.")
                return

            self._set_ui_state(True, status_text="Mengunduh Dokumen...", badge_type="running")
            self.btn_stop.config(text="🛑 Berhenti (Stop)")

            self.worker_thread = threading.Thread(
                target=self._run_single_worker,
                args=(url, out_dir),
                daemon=True,
            )
            self.worker_thread.start()

        # Tab 2: File of URLs
        elif current_tab == 2:
            filepath = self.file_path_var.get().strip()
            if not filepath or not os.path.exists(filepath):
                messagebox.showwarning("Peringatan", f"File daftar URL tidak ditemukan:\n{filepath}")
                return

            self._set_ui_state(True, status_text="Memproses File URL...", badge_type="running")
            self.btn_stop.config(text="🛑 Berhenti (Stop)")

            self.worker_thread = threading.Thread(
                target=self._run_file_worker,
                args=(filepath, out_dir, min_delay, max_delay),
                daemon=True,
            )
            self.worker_thread.start()

    # ---------------------------------------------------------------------------
    # Worker Threads
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
            self._log(f"\n❌ Terjadi kesalahan: {exc}")
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            status_text = "Dihentikan" if was_stopped or self.stop_event.is_set() else "Selesai"
            badge = "stopped" if was_stopped or self.stop_event.is_set() else "success"
            self.after(0, lambda: self._set_ui_state(False, status_text=status_text, badge_type=badge))

    def _run_single_worker(self, url, out_dir):
        old_stdout, old_stderr = sys.stdout, sys.stderr
        writer = QueueWriter(self.log_queue)
        sys.stdout, sys.stderr = writer, writer

        was_stopped = False
        try:
            self._log("=" * 60)
            self._log(f"🔗 Mengunduh satu dokumen dari URL: {url}")
            self._log(f"📁 Folder penyimpanan: {self._display_path(out_dir)}")
            self._log("=" * 60)

            saved_path, was_skipped = engine.download_scribd_document(
                url,
                output_dir=out_dir,
                close_driver=True,
                stop_event=self.stop_event,
            )
            if was_skipped:
                self._log(f"\nℹ️ Dokumen sudah pernah diunduh sebelumnya: {self._display_path(saved_path)}")
            else:
                self._log(f"\n🎉 Dokumen berhasil disimpan: {self._display_path(saved_path)}")
            self._open_output_folder()

        except KeyboardInterrupt:
            was_stopped = True
            self._log("\n🛑 Pengunduhan dokumen dihentikan oleh pengguna.")
        except Exception as exc:
            self._log(f"\n❌ Gagal mengunduh dokumen: {exc}")
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            status_text = "Dihentikan" if was_stopped or self.stop_event.is_set() else "Selesai"
            badge = "stopped" if was_stopped or self.stop_event.is_set() else "success"
            self.after(0, lambda: self._set_ui_state(False, status_text=status_text, badge_type=badge))

    def _run_file_worker(self, filepath, out_dir, min_delay, max_delay):
        old_stdout, old_stderr = sys.stdout, sys.stderr
        writer = QueueWriter(self.log_queue)
        sys.stdout, sys.stderr = writer, writer

        was_stopped = False
        try:
            self._log("=" * 60)
            self._log(f"📄 Membaca daftar URL dari file: {self._display_path(filepath)}")
            self._log(f"📁 Folder penyimpanan: {self._display_path(out_dir)}")
            self._log("=" * 60)

            urls = engine.load_urls_from_file(filepath)
            self._log(f"Berhasil membaca {len(urls)} tautan dari file.")

            stats = engine.bulk_download_documents(
                urls,
                output_dir=out_dir,
                min_delay=min_delay,
                max_delay=max_delay,
                stop_event=self.stop_event,
            )
            self._open_output_folder()

        except Exception as exc:
            self._log(f"\n❌ Gagal memproses file: {exc}")
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            status_text = "Dihentikan" if self.stop_event.is_set() else "Selesai"
            badge = "stopped" if self.stop_event.is_set() else "success"
            self.after(0, lambda: self._set_ui_state(False, status_text=status_text, badge_type=badge))


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
def main():
    app = MomoRescribdApp()
    app.mainloop()


if __name__ == "__main__":
    main()
