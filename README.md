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

- ⚡ **Eksekusi Multi-Kata Kunci Paralel (*True Concurrent Parallel Processing*)**:
  Menjalankan banyak kata kunci secara bersamaan (*side-by-side*) alih-alih berurutan. Setiap kata kunci menjalankan instance browser latar belakang (*headless Chrome*) tersendiri dengan profil dan memori terisolasi.
- 🖥️ **Konsol Log Terisolasi per Kata Kunci (*Dedicated Console Tabs*)**:
  Setiap kata kunci yang aktif memiliki tab konsol mandiri di area konsol. Log aktivitas tidak saling tercampur (*no log interleaving*). Pengguna dapat berpindah tab untuk memantau status masing-masing kata kunci secara *real-time*.
- 📁 **Folder Penyimpanan Kustom per Kata Kunci (*Custom Destination per Keyword*)**:
  Setiap kata kunci memiliki pengaturan direktori simpan tersendiri dengan tombol penjelajah folder (*file picker*). Dokumen antar kata kunci otomatis tersimpan ke subfolder terpisah yang rapi.
- 🛑 **Kontrol Henti Mandiri & Global (*Independent & Global Cancellation*)**:
  Pengguna dapat menghentikan salah satu kata kunci yang sedang berjalan tanpa mengganggu proses kata kunci lainnya, atau menghentikan seluruh tugas sekaligus dengan tombol "Hentikan Semua".
- ⏱️ **Rentang Jeda Acak (*Random Delay Range* 1000 – 5000 ms)**:
  Pengguna dapat mengatur rentang jeda antar pengunduhan (misalnya: Min 1.0 detik s/d Max 5.0 detik). Sistem akan menghasilkan angka acak dinamis (misal: 1.42s, 3.85s, 2.10s) sehingga terhindar dari deteksi bot maupun *rate-limiting*.
- 🎨 **Antarmuka Grafis Desktop Modern (UI/UX Redesign)**:
  Menggunakan CustomTkinter dengan dark-mode berstandar modern, tipografi jernih (SF Pro Display / Segoe UI / Menlo), kartu tugas interaktif, status badge dinamis (SIAP, MENCARI, MENGUNDUH, SELESAI, DIHENTIKAN), progress bar aktif, dan logo maskot astronot kustom.
- 📑 **Konversi PDF Asli & Bersih**:
  Menghilangkan seluruh elemen antarmuka yang mengganggu seperti toolbar, banner cookie, overlay langganan, dan watermark. Dokumen disimpan menjadi file PDF yang rapi dan dapat dibaca luring (*offline*).
- ⚡ **Deduplikasi Dokumen Cerdas (*Smart Resume & Deduplication*)**:
  Secara otomatis memeriksa file PDF yang sudah pernah diunduh di folder tujuan. Dokumen lama akan otomatis dilewati dan sistem akan mencari dokumen baru berikutnya agar tidak terjadi pengunduhan ganda.
- 🪟 **Siap Digunakan di Windows & macOS**:
  - **macOS**: Tersedia installer drag-and-drop `Momo_Rescribd.dmg` (didukung di macOS 11 Big Sur hingga macOS 15 Sequoia).
  - **Windows**: Disertai skrip otomatis `build_windows.bat` dan file spesifikasi `Momo_Rescribd.spec` untuk membuat file `dist\Momo Rescribd\Momo Rescribd.exe`.
- 🔒 **Privasi Terjaga**:
  Folder simpan default bersih (`~/Downloads/Momo_Rescribd`), tidak pernah mengekspos username sistem pada log konsol maupun antarmuka.
- 🔬 **Riset Solcoat — Laporan dari PDF Hasil Unduhan (tanpa AI)**:
  Tab **Riset Solcoat** membaca semua PDF di folder hasil unduhan per halaman (text layer, atau OCR untuk halaman scan / font rusak), menautkan angka ke peralatan (primary reformer, furnace, boiler, burner, dll.), lalu menyusun **laporan PDF** berformat hijau Solcoat dan **file Excel** berisi semua fakta beserta nama file dan nomor halaman sumbernya. Data bahasa OCR (±5 MB) diunduh otomatis saat pertama dipakai; Tesseract tidak perlu dipasang. Detail teknis, CLI, dan batasan ada di [`research/README.md`](research/README.md).

---

## 🔬 Cara Memakai Tab Kesiapan Hitung Furnace & Analisis Lanjutan

1. Unduh dokumen seperti biasa (mis. kata kunci "Pupuk Kaltim", "Petrokimia Gresik").
2. Buka tab **Kesiapan Hitung Furnace**, pastikan *Folder PDF sumber* mengarah ke folder hasil unduhan.
3. Klik **Mulai Riset**. Progres tampil di konsol tab *Kesiapan Hitung Furnace*.
4. Setelah selesai, klik **Buka Laporan PDF** atau **Buka Excel**. Hasil tersimpan di `<folder sumber>_Riset_Solcoat`.

Pemindaian pertama menjalankan OCR (±2 menit untuk ±5.000 halaman); pemindaian berikutnya memakai cache dan hanya butuh belasan detik. Semua angka berstatus **belum diverifikasi** — cocokkan ke halaman sumber sebelum dipakai di dokumen klien.

- **Progres & waktu**: bar progres per tahap (daftar PDF → ekstraksi/OCR → analisis → laporan), jumlah dokumen selesai, persentase, waktu berjalan, dan perkiraan sisa waktu. Setiap baris log di konsol diberi cap waktu `[mm:ss]`.
- **Riset sambil mengunduh**: tombol unduh tetap aktif selama riset berjalan. Saat ada unduhan, OCR otomatis memakai separuh inti CPU agar Chrome tetap lancar. PDF ditulis ke berkas `.part` lalu di-rename, sehingga riset tidak pernah membaca PDF setengah jadi; PDF yang selesai setelah riset dimulai ikut di riset berikutnya.
- **Hitung dengan Asumsi**: kalkulator dengan rumus yang sama persis dengan calculate.solcoat.com (diuji setara angka per angka terhadap `calc.js`). Pilih peralatan hasil riset atau isi manual; atur harga per galon (default Rp 85 jt), total luas dan porsi ceramic fiber, basis energi, harga bahan bakar, dan kurs (diambil otomatis beserta tanggalnya). Nilai yang **sudah diketahui** dari riset atau kurs otomatis **terkunci** — centang **Overwrite** pada baris itu untuk menggantinya. Hasil bisa disimpan sebagai PDF kalkulasi (skenario 2,5/5/7%, tanpa klaim garansi; harga per galon disembunyikan kecuali dipilih).
- **Verifikasi Fakta**: tabel semua angka hasil riset dengan pratinjau halaman sumber (nilai di-highlight). Tandai **benar/salah**, beri label **[U]/[V]/[A]**, koreksi nilai, dan catatan. Verifikasi tersimpan permanen (tidak hilang saat riset diulang); fakta salah tidak dipakai laporan maupun kalkulator, fakta terverifikasi diprioritaskan dan membawa labelnya.
- **Estimasi luas dari dimensi**: bila luas refraktori tidak ditemukan, kalkulator menghitung luas dari dimensi alat (silinder π·D·H + tutup, atau kotak dinding + atap) sebagai asumsi **[A]** lengkap dengan rumus dan sumber halaman; tersedia juga alat hitung manual di jendela kalkulator.
- **Mode PLTU**: laporan avoided cost 9 bagian dengan format baku Solcoat (skenario 15/30/50%, tanpa angka penghematan bahan bakar, waterwall otomatis di luar lingkup). Kinerja EAF/SOF/EFOR/NPHR per UP terisi dari Laporan Tahunan PLN NP 2025 dan terkunci (ganti lewat Overwrite); checklist dijalankan sebelum PDF `Solcoat_Calculation_<TAG>_KLIEN_<Rev>.pdf` dibuat.

**Tab Analisis Lanjutan** (menu terpisah, memakai folder sumber & hasil yang sama):
- **Laporan per Perusahaan**: PDF + Excel terpisah per klien di `<folder hasil>/Per_Perusahaan/` — dokumen, fakta, peralatan, dan kutipan klien lain tidak ikut.
- **Skor Prospek**: urutan prospek industri dari hasil riset (alat berapi tier A, fakta terverifikasi, harga gas, intensitas energi, sinyal strategis) dan PLTU dari data PLN NP 2025 (SOF, EAF, EFOR, bonus CFB); bisa diekspor ke Excel. Bobot adalah asumsi [A].
- **NPV Degradasi ε**: NPV, IRR, dan payback terdiskonto dengan emisivitas turun linear (default 0,98 → 0,80 dalam 7 tahun) terhadap substrat castable/fiber; konflik dengan klaim company profile dicatat di PDF.
- **Akurasi Ekstraksi**: presisi hasil ekstraksi per tingkat keyakinan, metode relasi, metode halaman, dan parameter, dihitung dari verifikasi analis (target minimal 100 fakta).
- **Impor Dokumen Klien**: pindai datasheet API 560 / refractory schedule klien sebagai sumber primer ke `<folder>_Riset_Klien`; baris tabel bergaya `Heat absorption, MMBtu/hr   45.20` dibaca sebagai spesifikasi (diuji dengan contoh sintetis — cocokkan dengan datasheet asli).
- Kamus riset kini juga mengenali istilah kilang (CDU/VDU/crude heater, cracking furnace), baja (reheating/walking beam furnace, hot blast stove), dan istilah datasheet API 560.

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
