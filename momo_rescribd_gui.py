#!/usr/bin/env python3
"""
Momo Rescribd - Graphical User Interface (GUI) for Scribd Downloader
Designed for non-programmers and everyday users on macOS.
"""

import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import scribd_engine as engine


class QueueWriter:
    """Redirects stdout and stderr to a thread-safe queue for the GUI."""

    def __init__(self, log_queue):
        self.queue = log_queue

    def write(self, text):
        if text:
            self.queue.put(text)

    def flush(self):
        pass


class MomoRescribdApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Momo Rescribd")
        self.geometry("780x680")
        self.minsize(680, 580)

        # Default storage folder is left empty by default
        self.output_dir_var = tk.StringVar(value="")

        self.mode_var = tk.StringVar(value="search")
        self.keyword_var = tk.StringVar(value="")
        self.single_url_var = tk.StringVar(value="")
        self.file_path_var = tk.StringVar(value="")
        self.limit_var = tk.IntVar(value=5)

        self.is_running = False
        self.worker_thread = None
        self.log_queue = queue.Queue()

        self._apply_styles()
        self._build_ui()
        self._poll_log_queue()

    def _apply_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use("aqua")  # Native macOS appearance
        except Exception:
            pass

        style.configure("Header.TLabel", font=("SF Pro Text", 20, "bold"), foreground="#1c263d")
        style.configure("Subheader.TLabel", font=("SF Pro Text", 12), foreground="#57617a")
        style.configure("Section.TLabelframe.Label", font=("SF Pro Text", 12, "bold"), foreground="#1c263d")
        style.configure("Action.TButton", font=("SF Pro Text", 13, "bold"), padding=8)

    def _build_ui(self):
        main_frame = ttk.Frame(self, padding="18 16 18 16")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. Header Area
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 14))

        title_lbl = ttk.Label(header_frame, text="📚 Momo Rescribd", style="Header.TLabel")
        title_lbl.pack(anchor=tk.W)

        subtitle_lbl = ttk.Label(
            header_frame,
            text="Unduh Dokumen Scribd Sebagai PDF Bersih — Cepat, Otomatis, & Tanpa Akun",
            style="Subheader.TLabel",
        )
        subtitle_lbl.pack(anchor=tk.W, pady=(2, 0))

        # 2. Mode Selection Frame
        mode_frame = ttk.LabelFrame(main_frame, text=" 1. Pilih Cara Pengunduhan ", padding="12 8 12 10")
        mode_frame.pack(fill=tk.X, pady=(0, 10))

        r1 = ttk.Radiobutton(
            mode_frame,
            text="🔍 Cari Kata Kunci & Download Otomatis (Rekomendasi)",
            variable=self.mode_var,
            value="search",
            command=self._on_mode_change,
        )
        r1.pack(anchor=tk.W, pady=2)

        r2 = ttk.Radiobutton(
            mode_frame,
            text="🔗 Download dari 1 Link Dokumen Scribd",
            variable=self.mode_var,
            value="single",
            command=self._on_mode_change,
        )
        r2.pack(anchor=tk.W, pady=2)

        r3 = ttk.Radiobutton(
            mode_frame,
            text="📄 Download Banyak dari File Teks (Daftar URL)",
            variable=self.mode_var,
            value="file",
            command=self._on_mode_change,
        )
        r3.pack(anchor=tk.W, pady=2)

        # 3. Input Parameters Frame
        self.input_frame = ttk.LabelFrame(main_frame, text=" 2. Detail Dokumen ", padding="12 10 12 12")
        self.input_frame.pack(fill=tk.X, pady=(0, 10))

        # Input Row (Keyword / URL / File)
        self.entry_label = ttk.Label(self.input_frame, text="Kata Kunci Dokumen:")
        self.entry_label.grid(row=0, column=0, sticky=tk.W, pady=4)

        self.input_entry = ttk.Entry(self.input_frame, font=("SF Pro Text", 12))
        self.input_entry.grid(row=0, column=1, columnspan=2, sticky=tk.EW, padx=(6, 0), pady=4)
        self.input_frame.columnconfigure(1, weight=1)

        self.btn_browse_file = ttk.Button(self.input_frame, text="Pilih File...", command=self._browse_file)

        # Limit Row
        self.limit_label = ttk.Label(self.input_frame, text="Jumlah Dokumen:")
        self.limit_label.grid(row=1, column=0, sticky=tk.W, pady=6)

        limit_box = ttk.Spinbox(
            self.input_frame,
            from_=1,
            to=100,
            textvariable=self.limit_var,
            width=8,
            font=("SF Pro Text", 12),
        )
        limit_box.grid(row=1, column=1, sticky=tk.W, padx=(6, 0), pady=6)

        # Folder Row
        ttk.Label(self.input_frame, text="Folder Simpan:").grid(row=2, column=0, sticky=tk.W, pady=4)
        folder_entry = ttk.Entry(self.input_frame, textvariable=self.output_dir_var, font=("SF Pro Text", 11))
        folder_entry.grid(row=2, column=1, sticky=tk.EW, padx=(6, 6), pady=4)

        btn_browse_folder = ttk.Button(self.input_frame, text="Pilih Folder...", command=self._browse_folder)
        btn_browse_folder.grid(row=2, column=2, sticky=tk.E, pady=4)

        hint_label = ttk.Label(
            self.input_frame,
            text="(Kosongkan untuk otomatis menyimpan ke folder Downloads/Momo_Rescribd)",
            font=("SF Pro Text", 10),
            foreground="#6b7280",
        )
        hint_label.grid(row=3, column=1, columnspan=2, sticky=tk.W, padx=(6, 0), pady=(0, 4))

        # 4. Action Buttons Frame
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 10))

        self.btn_start = ttk.Button(
            btn_frame,
            text="🚀 Mulai Download",
            style="Action.TButton",
            command=self._start_download,
        )
        self.btn_start.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_open_folder = ttk.Button(
            btn_frame,
            text="📂 Buka Folder Hasil",
            padding=8,
            command=self._open_output_folder,
        )
        self.btn_open_folder.pack(side=tk.LEFT)

        self.status_label = ttk.Label(
            btn_frame,
            text="Siap digunakan.",
            font=("SF Pro Text", 11, "italic"),
            foreground="#57617a",
        )
        self.status_label.pack(side=tk.RIGHT, padx=6)

        # 5. Live Console Log Frame
        log_frame = ttk.LabelFrame(main_frame, text=" 3. Status & Log Progres ", padding="8 8 8 8")
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = ScrolledText(
            log_frame,
            wrap=tk.WORD,
            font=("Menlo", 10),
            background="#ffffff",
            foreground="#1c263d",
            padx=6,
            pady=6,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Set default focus
        self._on_mode_change()
        self.input_entry.focus()

    def _on_mode_change(self):
        mode = self.mode_var.get()
        if mode == "search":
            self.entry_label.config(text="Kata Kunci Dokumen:")
            self.input_entry.config(textvariable=self.keyword_var)
            self.btn_browse_file.grid_remove()
            self.limit_label.grid()
        elif mode == "single":
            self.entry_label.config(text="Link URL Scribd:")
            self.input_entry.config(textvariable=self.single_url_var)
            self.btn_browse_file.grid_remove()
            self.limit_label.grid_remove()
        elif mode == "file":
            self.entry_label.config(text="File Daftar URL:")
            self.input_entry.config(textvariable=self.file_path_var)
            self.btn_browse_file.grid(row=0, column=2, padx=(4, 0), sticky=tk.E)
            self.limit_label.grid_remove()

    def _browse_file(self):
        file_selected = filedialog.askopenfilename(
            title="Pilih File Daftar URL",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
        )
        if file_selected:
            self.file_path_var.set(file_selected)

    def _browse_folder(self):
        folder_selected = filedialog.askdirectory(
            title="Pilih Folder Penyimpanan PDF",
            initialdir=self.output_dir_var.get(),
        )
        if folder_selected:
            self.output_dir_var.set(folder_selected)

    def _get_effective_output_dir(self):
        val = self.output_dir_var.get().strip()
        if val:
            path = os.path.expanduser(val)
        else:
            path = os.path.expanduser("~/Downloads/Momo_Rescribd")
        os.makedirs(path, exist_ok=True)
        return path

    def _display_path(self, path):
        if not path:
            return ""
        home = os.path.expanduser("~")
        abs_path = os.path.abspath(os.path.expanduser(str(path)))
        if abs_path.startswith(home):
            return "~" + abs_path[len(home):]
        return abs_path

    def _open_output_folder(self):
        folder = self._get_effective_output_dir()
        if os.path.exists(folder):
            if sys.platform == "darwin":
                os.system(f'open "{os.path.abspath(folder)}"')
            else:
                os.system(f'start "" "{os.path.abspath(folder)}"')
        else:
            messagebox.showinfo("Informasi", f"Folder belum ada:\n{self._display_path(folder)}")

    def _poll_log_queue(self):
        """Periodically reads messages from the worker thread log queue."""
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

    def _set_ui_state(self, running):
        self.is_running = running
        if running:
            self.btn_start.config(state=tk.DISABLED, text="⏳ Sedang Mengunduh...")
            self.status_label.config(text="Sedang berjalan...", foreground="#0d6069")
        else:
            self.btn_start.config(state=tk.NORMAL, text="🚀 Mulai Download")
            self.status_label.config(text="Selesai.", foreground="#2e7d32")

    def _start_download(self):
        if self.is_running:
            return

        mode = self.mode_var.get()
        out_dir = self._get_effective_output_dir()

        if mode == "search":
            keyword = self.keyword_var.get().strip()
            if not keyword:
                messagebox.showwarning("Peringatan", "Silakan masukkan kata kunci pencarian.")
                return
            try:
                limit = int(self.limit_var.get())
                if limit <= 0:
                    raise ValueError
            except Exception:
                messagebox.showwarning("Peringatan", "Jumlah dokumen harus angka minimal 1.")
                return

            self._set_ui_state(True)
            self.worker_thread = threading.Thread(
                target=self._run_search_and_download,
                args=(keyword, limit, out_dir),
                daemon=True,
            )
            self.worker_thread.start()

        elif mode == "single":
            url = self.single_url_var.get().strip()
            if not url:
                messagebox.showwarning("Peringatan", "Silakan masukkan link Scribd.")
                return

            self._set_ui_state(True)
            self.worker_thread = threading.Thread(
                target=self._run_single_download,
                args=(url, out_dir),
                daemon=True,
            )
            self.worker_thread.start()

        elif mode == "file":
            filepath = self.file_path_var.get().strip()
            if not filepath or not os.path.exists(filepath):
                messagebox.showwarning("Peringatan", f"File daftar URL tidak ditemukan:\n{filepath}")
                return

            self._set_ui_state(True)
            self.worker_thread = threading.Thread(
                target=self._run_file_download,
                args=(filepath, out_dir),
                daemon=True,
            )
            self.worker_thread.start()

    def _run_search_and_download(self, keyword, limit, out_dir):
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        writer = QueueWriter(self.log_queue)
        sys.stdout = writer
        sys.stderr = writer

        try:
            self._log("=" * 60)
            self._log(f"🔎 Mencari dokumen untuk kata kunci: '{keyword}'")
            self._log(f"🎯 Target jumlah dokumen baru: {limit}")
            self._log(f"📁 Folder penyimpanan: {self._display_path(out_dir)}")
            self._log("=" * 60)

            # Cek file yang sudah ada sebelumnya
            existing_ids = engine.get_downloaded_document_ids(out_dir)
            if existing_ids:
                self._log(f"ℹ️ Ditemukan {len(existing_ids)} file PDF yang sudah pernah diunduh.")
                self._log("   Sistem akan otomatis melewati file lama dan mencari dokumen baru.\n")

            docs = engine.search_scribd_documents(
                keyword,
                limit=limit,
                existing_ids=existing_ids,
                close_driver=True,
            )

            if not docs:
                self._log(f"❌ Tidak ditemukan dokumen baru untuk kata kunci '{keyword}'.")
                messagebox.showinfo("Informasi", f"Tidak ditemukan dokumen baru untuk kata kunci '{keyword}'.")
                return

            engine.save_search_results_file(keyword, docs, output_dir=out_dir)

            self._log(f"\n🚀 Memulai bulk download {len(docs)} file PDF...")
            stats = engine.bulk_download_documents(docs, output_dir=out_dir, delay_between=2.5)

            self._log(f"\n🎉 Download Selesai! Berhasil: {stats['success']}, Gagal: {stats['failed']}")
            self._open_output_folder()

        except Exception as exc:
            self._log(f"\n❌ Terjadi kesalahan: {exc}")
            messagebox.showerror("Error", f"Terjadi kesalahan saat download:\n{exc}")
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            self.after(0, lambda: self._set_ui_state(False))

    def _run_single_download(self, url, out_dir):
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        writer = QueueWriter(self.log_queue)
        sys.stdout = writer
        sys.stderr = writer

        try:
            self._log("=" * 60)
            self._log(f"🔗 Mengunduh dokumen dari URL: {url}")
            self._log(f"📁 Folder penyimpanan: {self._display_path(out_dir)}")
            self._log("=" * 60)

            saved_path, was_skipped = engine.download_scribd_document(
                url,
                output_dir=out_dir,
                close_driver=True,
            )
            if was_skipped:
                self._log(f"\nℹ️ Dokumen sudah pernah diunduh: {self._display_path(saved_path)}")
            else:
                self._log(f"\n🎉 Dokumen berhasil disimpan: {self._display_path(saved_path)}")

            self._open_output_folder()

        except Exception as exc:
            self._log(f"\n❌ Terjadi kesalahan: {exc}")
            messagebox.showerror("Error", f"Gagal mengunduh dokumen:\n{exc}")
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            self.after(0, lambda: self._set_ui_state(False))

    def _run_file_download(self, filepath, out_dir):
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        writer = QueueWriter(self.log_queue)
        sys.stdout = writer
        sys.stderr = writer

        try:
            self._log("=" * 60)
            self._log(f"📄 Membaca daftar URL dari file: {self._display_path(filepath)}")
            self._log(f"📁 Folder penyimpanan: {self._display_path(out_dir)}")
            self._log("=" * 60)

            urls = engine.load_urls_from_file(filepath)
            self._log(f"Berhasil membaca {len(urls)} tautan dari file.")

            stats = engine.bulk_download_documents(urls, output_dir=out_dir, delay_between=2.5)
            self._log(f"\n🎉 Selesai! Berhasil: {stats['success']}, Gagal: {stats['failed']}")
            self._open_output_folder()

        except Exception as exc:
            self._log(f"\n❌ Terjadi kesalahan: {exc}")
            messagebox.showerror("Error", f"Gagal memproses file:\n{exc}")
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            self.after(0, lambda: self._set_ui_state(False))


def main():
    app = MomoRescribdApp()
    app.mainloop()


if __name__ == "__main__":
    main()
