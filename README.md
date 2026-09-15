# Momo Rescribd — Scribd Bulk Search & Downloader

<p align="center">
  <b>Unduh Dokumen Scribd Sebagai PDF Bersih — Pencarian Otomatis Kata Kunci, Bulk Download, & Antarmuka Grafis Praktis</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey?style=for-the-badge" alt="Multi-Platform">
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="MIT License">
</p>

---

## 📖 Apa Itu Momo Rescribd?

**Momo Rescribd (`scribd_bulk_search_dl`)** adalah perangkat lunak otomasi pintar yang dirancang untuk mencari, mengekstrak, dan mengunduh dokumen dari Scribd secara massal (*bulk download*) dan menyimpannya sebagai file **PDF berkualitas tinggi**.

Aplikasi ini dibuat agar dapat digunakan oleh siapa saja — mulai dari pengguna awam non-teknis yang menginginkan kemudahan klik tanpa terminal, hingga pengembang atau peneliti yang membutuhkan antarmuka *Command-Line Interface* (CLI) untuk otomatisasi skala besar.

---

## ✨ Fitur Utama

- 🔍 **Pencarian Kata Kunci Otomatis (*Smart Keyword Query*)**:
  Cukup ketikkan kata kunci yang Anda cari (misalnya: `"Pupuk Kaltim"`, `"Akuntansi Keuangan"`, `"Data Science"`), sistem akan otomatis menjelajahi direktori pencarian Scribd (termasuk pagination halaman 1, 2, 3, dst.) hingga mencapai target jumlah dokumen yang Anda inginkan.
- 📑 **Konversi PDF Rapi & Bersih**:
  Menghilangkan elemen antarmuka yang mengganggu seperti toolbar, banner cookie, overlay berlangganan, serta iklan. Dokumen dikonversi menjadi lembaran PDF asli yang jernih.
- ⚡ **Deduplikasi Dokumen (*Smart Resume & Deduplication*)**:
  Sistem secara otomatis memeriksa dokumen yang sudah pernah diunduh sebelumnya di folder tujuan. Jika dokumen sudah ada, sistem melewatinya dan otomatis mencari dokumen baru berikutnya agar tidak terjadi pengunduhan ganda atau pemborosan kuota.
- 🖥️ **Antarmuka Grafis Modern (GUI)**:
  Dilengkapi antarmuka desktop **Momo Rescribd** yang mudah digunakan tanpa perlu mengetik perintah apapun di terminal.
- 📦 **Installer Standalone macOS (.app & .dmg)**:
  Tersedia dalam format `.dmg` siap pasang yang mendukung macOS 11 (Big Sur), macOS 12 (Monterey), macOS 13 (Ventura), macOS 14 (Sonoma), hingga macOS 15 (Sequoia).
- 🔄 **Tiga Mode Pengunduhan Fleksibel**:
  1. **Cari Kata Kunci & Download Otomatis** (Paling praktis).
  2. **Download dari 1 Link URL Tunggal**.
  3. **Download Massal dari File Teks** (daftar link `urls.txt`).
- 🔒 **Privasi Terjaga**:
  Folder penyimpanan default aman dan bersih (tanpa mengekspos username sistem), pengguna bebas memilih folder penyimpanan sendiri.

---

## 🚀 Cara Penggunaan

### Cara 1: Menggunakan Aplikasi Desktop macOS (Paling Direkomendasikan)

1. Buka file instalasi `Momo_Rescribd.dmg`.
2. Geser / Drag ikon **Momo Rescribd** ke folder **Applications**.
3. Buka **Momo Rescribd** dari Launchpad atau Finder.
4. Pilih cara pengunduhan:
   - Masukkan kata kunci pencarian dan jumlah target dokumen.
   - Atau tempelkan link URL dokumen Scribd.
   - Tentukan folder penyimpanan (atau biarkan kosong untuk otomatis menyimpan ke folder `Downloads/Momo_Rescribd`).
5. Klik tombol **🚀 Mulai Download**.
6. Setelah selesai, klik **📂 Buka Folder Hasil** untuk langsung melihat semua file PDF yang berhasil diunduh.

---

### Cara 2: Menggunakan Launcher Cepat (`Mulai_Download.command`)

Bagi pengguna Mac yang ingin menjalankan skrip secara langsung:
1. Klik 2x file `Mulai_Download.command` di Finder.
2. Terminal akan terbuka dan menampilkan menu pilihan interaktif berbahasa Indonesia.
3. Masukkan kata kunci pencarian dan jumlah dokumen yang diinginkan.
4. Sistem akan otomatis mengunduh dan membuka folder hasil di Finder saat selesai.

---

### Cara 3: Menggunakan Command-Line (CLI)

Bagi pengembang atau pengguna tingkat lanjut:

#### 1. Persiapan Lingkungan
Pastikan Anda memiliki **Python 3.11+** dan browser **Google Chrome**:
```bash
# Clone repository
git clone https://github.com/momochan32/scribd_bulk_search_dl.git
cd scribd_bulk_search_dl

# Buat virtual environment & install dependensi
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### 2. Menjalankan Antarmuka GUI
```bash
python3 momo_rescribd_gui.py
```

#### 3. Menjalankan CLI Interaktif
```bash
python3 scribd-downloader.py
```

#### 4. Menjalankan Langsung via Argumen Terminal
```bash
# Cari kata kunci dan unduh 10 dokumen sekaligus
python3 scribd-downloader.py --search "Manajemen Bisnis" --limit 10

# Download 1 dokumen dari URL spesifik
python3 scribd-downloader.py --url "https://www.scribd.com/document/123456789/Judul-Dokumen"

# Bulk download dari file teks berisi daftar tautan
python3 scribd-downloader.py --file urls.txt --delay 2.5
```

---

## ⚙️ Ringkasan Opsi CLI

| Argumen | Opsi Pendek | Keterangan | Default |
|---|---|---|---|
| `--search` | `-s` | Kata kunci pencarian di Scribd | `None` |
| `--limit` | `-l` | Jumlah maksimal dokumen baru yang diunduh | `10` |
| `--url` | `-u` | Mengunduh satu tautan dokumen Scribd | `None` |
| `--file` | `-f` | Path ke file teks berisi daftar URL | `None` |
| `--output` | `-o` | Folder direktori tujuan penyimpanan PDF | `output` |
| `--delay` | `-d` | Jeda waktu (detik) antar unduhan file | `2.5` |
| `--no-download` | | Hanya mencari & menyimpan URL ke file `.txt` | `False` |

---

## 🛠️ Cara Kerja Sistem (How It Works)

1. **Query & Discovery**: Mengakses mesin pencari Scribd dengan pagination bertingkat dan mengumpulkan URL dokumen yang unik.
2. **Deduplication Check**: Memindai ID dokumen pada folder tujuan agar file yang sudah pernah diunduh tidak diambil kembali.
3. **Headless Engine**: Menjalankan Google Chrome secara otomatis di latar belakang (*headless mode*).
4. **DOM Sanitization**: Membersihkan seluruh banner, pelindung, dan antarmuka baca untuk menyisakan konten dokumen murni.
5. **Page Rendering & CDP Print**: Mengukur dimensi tiap halaman dokumen dan mencetak lembaran dokumen secara presisi melalui Chrome DevTools Protocol (CDP).
6. **PDF Assembly**: Menggabungkan seluruh lembar dokumen yang telah dirender menjadi satu file PDF utuh menggunakan `pypdf`.

---

## 📄 Lisensi (License)

Proyek ini dilisensikan di bawah lisensi **MIT License** — Anda bebas menggunakan, memodifikasi, dan mendistribusikan kode ini untuk keperluan yang sah sesuai ketentuan lisensi.

---

## ⚠️ Disclaimer (Pernyataan Penyangkalan)

> **PENTING**:
> Perangkat lunak ini dibuat dan dipublikasikan **hanya sebagai media pembelajaran saja (*educational purpose*)** dalam bidang otomasi peramban web (*browser automation*) dan manipulasi dokumen digital, serta **bukan dilakukan sebagai kegiatan ilegal**.
> 
> Harap selalu menghormati hak cipta (*copyright*), hak kekayaan intelektual penulis asli, serta Syarat & Ketentuan Layanan (*Terms of Service*) dari platform Scribd. 
> 
> **Penulis/Pengembang tidak bertanggung jawab sedikit pun atas segala tindakan, kerugian, pelanggaran hak cipta, atau penyalahgunaan apa pun yang dilakukan oleh pengguna.** Segala risiko dan konsekuensi hukum yang timbul dari penggunaan alat ini sepenuhnya merupakan tanggung jawab masing-masing individu pengguna.
