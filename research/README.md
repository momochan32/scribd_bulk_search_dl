# Riset Sumber PDF Solcoat (tanpa AI)

Membaca folder PDF hasil unduhan Momo Rescribd, lalu menghasilkan:

| Keluaran | Isi |
|---|---|
| `Laporan_Riset_Solcoat_<waktu>.pdf` | Laporan hijau Solcoat untuk tim teknis & analis: peralatan target, parameter + halaman sumber, peta kebutuhan data, indikasi komersial, kutipan strategis, daftar verifikasi |
| `Data_Riset_Solcoat_<waktu>.xlsx` | Semua fakta (termasuk keyakinan rendah), bisa difilter per perusahaan/alat/parameter |
| `research.db` | SQLite: teks semua halaman (pencarian penuh), fakta, peralatan, cache OCR |

## Pasang (sekali)

```bash
cd research
./setup_ocr.sh        # Tesseract + bahasa Indonesia/Inggris + virtualenv
```

## Pakai

```bash
# Pindai folder (subfolder = topik, mis. Pupuk_Kaltim/, Petrokimia_Gresik/)
.venv/bin/python -m solcoat_research scan ~/Downloads/Momo_Rescribd --out output

# Cari teks di semua halaman yang sudah dipindai
.venv/bin/python -m solcoat_research search output '"primary reformer" AND burner'
```

Pemindaian ulang memakai cache: OCR hanya dijalankan untuk PDF baru.

## Cara kerja

1. **Per halaman:** text layer dipakai bila bisa dipercaya. Halaman kosong, hasil scan, atau dengan font rusak
   (`koe8isien`, `&rilling`) otomatis dibaca OCR.
2. **Normalisasi:** ligatur hilang, satuan OCR (`oC`, `kg/cm'G`, `Nm'/jam`, `m?`), format angka Indonesia/Inggris.
3. **Relasi angka → peralatan**, tiga lapis:
   - *tinggi* — blok `Kunci : nilai` di bawah judul alat
   - *sedang* — alat disebut di kalimat yang sama
   - *rendah* — alat terdekat sebelumnya
4. **Validasi:** rentang wajar per parameter, LHV per bahan bakar, angka ambigu, angka OCR,
   nilai yang berbeda antar sumber.
5. **Deduplikasi:** file identik (SHA-256) dan isi yang 90%+ sama.

## Menyesuaikan tanpa menyentuh kode

Edit `solcoat_research/lexicon.yaml`: peralatan (tier A/B/C), sinonim parameter, rentang wajar, perusahaan,
pabrik → perusahaan, jenis sumber, kata kunci strategis. Jalankan tes setelah mengubah:

```bash
.venv/bin/python -m pytest -q tests
```

## Batasan yang perlu diketahui

- Status semua angka: **belum diverifikasi**. Jangan beri label `[U]` sebelum dicek ke halaman sumber.
- Laporan KP mahasiswa = sumber sekunder.
- Tabel scan tanpa garis, grafik, gambar, dan GA drawing tidak terbaca sebagai angka.
- Relasi lintas halaman lemah; "desain" vs "aktual" hanya dikenali dari kata kunci.
- Data inti Solcoat (luas refraktori, heat duty, suhu flue gas, konsumsi bahan bakar per heater) hampir tidak
  pernah ada di dokumen publik. Laporan menandai kekosongan ini agar diminta langsung ke klien.

## Hitung dengan Asumsi (kalkulator Solcoat)

`calculator.py` adalah port dari `Solcoat-Fuel-Energy-Saving-App/src/utils/calc.js`. Kesetaraannya diuji di
`tests/test_calculator.py` terhadap keluaran JavaScript asli. Bila `calc.js` berubah, perbarui port lalu buat
ulang fixture:

```bash
node tests/fixtures/make_calc_parity.mjs ~/Documents/Solcoat-Fuel-Energy-Saving-App/src/utils/calc.js \
  > tests/fixtures/calc_js_parity.json
.venv/bin/python -m pytest -q tests/test_calculator.py
```

Aturan form (`calc_form.py`): nilai dari riset (`calc_prefill.py`) atau kurs otomatis (`fx.py`) terkunci dan hanya
bisa diganti setelah kotak Overwrite dicentang; centang tanpa isian valid ditolak. Default mengikuti Project
Instructions Solcoat v2.6 (Rp 85 jt/galon, 3,50/2,50 m²/galon, 8.760 jam, skenario 2,5/5/7%).
