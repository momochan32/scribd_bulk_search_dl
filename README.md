# Momo Rescribd — Scribd Bulk Search & Downloader

<p align="center">
  <b>Unduh Dokumen Scribd Sebagai PDF Bersih — Multi-Keyword Search, Stop/Cancel Instan, Jeda Acak Bebas Blokir, & GUI Modern Lintas Platform</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Platform-macOS%20%7C%20Windows%20%7C%20Linux-success?style=for-the-badge" alt="Multi-Platform">
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="MIT License">
</p>

---

## 📖 Apa Itu Momo Rescribd?

**Momo Rescribd (`scribd_bulk_search_dl`)** adalah perangkat lunak otomasi pintar yang dirancang untuk mencari, mengekstrak, dan mengunduh dokumen dari Scribd secara massal (*bulk download*) dan menyimpannya sebagai file **PDF berkualitas tinggi**.

Aplikasi ini didesain dengan antarmuka grafis (GUI) modern yang elegan dan ramah pengguna awam, serta dapat dikompilasi menjadi **file installer macOS (`.dmg`)** maupun **aplikasi mandiri Windows (`.exe`)**.

---

## ✨ Fitur Utama Terbaru

- 🔍 **Multi-Pencarian Kata Kunci Massal (*Multi-Keyword Search Queue*)**:
  Mendukung input banyak kata kunci sekaligus (dipisahkan baris baru atau koma, misal: `Pupuk Kaltim`, `Petrokimia Gresik`, `Pupuk Indonesia`). Sistem secara otomatis memproses dan mengunduh dokumen per kata kunci secara berurutan.
- 🛑 **Fitur Berhenti Seketika (*Instant Stop / Cancellation*)**:
  Tersedia tombol **🛑 Berhenti (Stop)** yang merespons secara langsung. Peramban Chrome latar belakang dan file temporer akan langsung ditutup dan dibersihkan dengan aman tanpa meninggalkan proses menggantung.
- ⏱️ **Rentang Jeda Acak (*Random Delay Range* 1000 – 5000 ms)**:
  Pengguna dapat mengatur rentang jeda antar pengunduhan (misalnya: Min 1.0 detik s/d Max 5.0 detik). Sistem akan menghasilkan angka acak dinamis (misal: 1.42s, 3.85s, 2.10s) sehingga terhindar dari deteksi bot maupun *rate-limiting*.
- 🎨 **Antarmuka Grafis Desktop Modern (UI/UX Redesign)**:
  Tampilan kartu modern berbasis Slate & Indigo, tab navigasi rapi, penghitung kata kunci otomatis, status badge indikator (🟢 Siap, 🟡 Berjalan, 🛑 Dihentikan, 🎉 Selesai), progress bar aktif, dan konsol log terminal bergaya dark-mode.
- 📑 **Konversi PDF Asli & Bersih**:
  Menghilangkan seluruh elemen antarmuka yang mengganggu seperti toolbar, banner cookie, overlay langganan, dan watermark. Dokumen disimpan menjadi file PDF yang rapi dan dapat dibaca luring (*offline*).
- ⚡ **Deduplikasi Dokumen Cerdas (*Smart Resume & Deduplication*)**:
  Secara otomatis memeriksa file PDF yang sudah pernah diunduh di folder tujuan. Dokumen lama akan otomatis dilewati dan sistem akan mencari dokumen baru berikutnya agar tidak terjadi pengunduhan ganda.
- 🪟 **Siap Digunakan di Windows & macOS**:
  - **macOS**: Tersedia installer drag-and-drop `Momo_Rescribd.dmg` (didukung di macOS 11 Big Sur hingga macOS 15 Sequoia).
  - **Windows**: Disertai skrip otomatis `build_windows.bat` dan file spesifikasi `Momo_Rescribd.spec` untuk membuat file `dist\Momo Rescribd\Momo Rescribd.exe`.
- 🔒 **Privasi Terjaga**:
  Folder simpan default bersih (`~/Downloads/Momo_Rescribd`), tidak pernah mengekspos username sistem pada log konsol maupun antarmuka.

---

## 🚀 Cara Penggunaan

### 🍎 Pengguna macOS

#### Opsi 1: Menggunakan Installer DMG (Paling Praktis)
1. Buka file installer `Momo_Rescribd.dmg`.
2. Geser ikon **Momo Rescribd** ke folder **Applications**.
3. Buka **Momo Rescribd** dari Launchpad atau Applications.
4. Masukkan kata kunci, tentukan target dokumen & rentang jeda acak, lalu klik **🚀 Mulai Download**.
5. Untuk menghentikan proses kapan saja, cukup klik **🛑 Berhenti (Stop)**.

#### Opsi 2: Menggunakan Launcher `Mulai_Download.command`
1. Klik 2x file `Mulai_Download.command` di Finder.
2. Terminal interaktif berbahasa Indonesia akan terbuka otomatis.

---

### 🪟 Pengguna Windows

#### Opsi 1: Menjalankan / Membangun File .EXE Sekali Klik
1. Pastikan **Python 3.10+** dan browser **Google Chrome** sudah terpasang.
2. Klik 2x file **`build_windows.bat`**.
3. Skrip akan otomatis menyiapkan virtual environment, memasang dependensi, dan mengompilasi aplikasi menjadi:
   ```text
   dist\Momo Rescribd\Momo Rescribd.exe
   ```
4. Buka file `Momo Rescribd.exe` untuk menjalankan antarmuka desktop.

#### Opsi 2: Menjalankan Langsung via Terminal PowerShell / CMD
```powershell
# Clone repositori
git clone https://github.com/momochan32/scribd_bulk_search_dl.git
cd scribd_bulk_search_dl

# Siapkan environment
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Jalankan GUI
python momo_rescribd_gui.py
```

---

### 💻 Penggunaan via Command-Line Interface (CLI)

Bagi pengembang atau kebutuhan otomatisasi server:

```bash
# 1. Cari satu kata kunci dan unduh 10 dokumen sekaligus
python scribd-downloader.py --search "Manajemen Keuangan" --limit 10

# 2. Unduh dari 1 tautan URL spesifik
python scribd-downloader.py --url "https://www.scribd.com/document/123456789/Judul-Dokumen"

# 3. Bulk download dari file teks berisi daftar link (urls.txt)
python scribd-downloader.py --file urls.txt --delay 3.0
```

---

## ⚙️ Ringkasan Parameter & Pengaturan

| Fitur | Keterangan | Nilai Default |
|---|---|---|
| **Target Dokumen** | Jumlah dokumen baru per kata kunci | `5` |
| **Min Jeda Acak** | Batas minimal jeda antar unduhan dokumen | `1.0 detik` (1000 ms) |
| **Max Jeda Acak** | Batas maksimal jeda antar unduhan dokumen | `5.0 detik` (5000 ms) |
| **Folder Simpan** | Lokasi penyimpanan file PDF | `~/Downloads/Momo_Rescribd` |
| **Stop Event** | Membatalkan pencarian / pengunduhan secara aman | Tombol `🛑 Berhenti` |

---

## 🛠️ Arsitektur Sistem

```text
[Input Pengguna: Multi-Keywords / URL / File]
                     │
                     ▼
       [Momo Rescribd GUI / CLI Engine]
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
 [Smart Query & Search]    [Deduplication Scanner]
 (Pagination & Links)      (Memeriksa file di folder tujuan)
         │                       │
         └───────────┬───────────┘
                     ▼
         [Headless Chrome CDP Engine]
    (Sanitasi DOM, Print-to-PDF per lembar)
                     │
                     ▼
          [Random Delay Regulator]
           (Jeda acak 1.0s - 5.0s)
                     │
                     ▼
       [pypdf Disk-Spooled Assembler]
                     │
                     ▼
          [File PDF Bersih & Utuh]
```

---

## 📄 Lisensi (License)

Proyek ini dilisensikan di bawah lisensi **MIT License** — lihat berkas [LICENSE](LICENSE) untuk informasi lebih lanjut.

---

## ⚠️ Disclaimer (Pernyataan Penyangkalan)

> **PENTING**:
> Perangkat lunak ini dibuat dan dipublikasikan **hanya sebagai media pembelajaran saja (*educational purpose*)** dalam bidang otomasi peramban web (*browser automation*) dan manipulasi dokumen digital, serta **bukan dilakukan sebagai kegiatan ilegal**.
> 
> Harap selalu menghormati hak cipta (*copyright*), hak kekayaan intelektual penulis dokumen asli, serta Syarat & Ketentuan Layanan (*Terms of Service*) dari platform Scribd.
> 
> **Penulis/Pengembang tidak bertanggung jawab sedikit pun atas segala tindakan, kerugian, pelanggaran hak cipta, atau penyalahgunaan apa pun yang dilakukan oleh pengguna.** Segala risiko dan konsekuensi hukum yang timbul dari penggunaan alat ini sepenuhnya merupakan tanggung jawab masing-masing individu pengguna.
