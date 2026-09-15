#!/bin/bash
# ==========================================================
# Scribd Downloader Launcher untuk Mac
# Bisa diklik 2x langsung dari Finder / Desktop
# ==========================================================

cd "$(dirname "$0")"

# Cek apakah virtual environment sudah siap
if [ ! -f ".venv/bin/python3" ]; then
    echo "⚙️ Menyiapkan sistem pertama kali..."
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
fi

# Jalankan script downloader dengan Python venv yang benar
.venv/bin/python3 scribd-downloader.py "$@"

EXIT_CODE=$?
echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Selesai!"
else
    echo "⚠️ Proses selesai atau dihentikan."
fi

# Tahan jendela terminal agar tidak langsung tertutup saat diklik 2x dari Finder
echo ""
read -p "Tekan [Enter] untuk menutup jendela ini..."
