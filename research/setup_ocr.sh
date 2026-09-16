#!/usr/bin/env bash
# Menyiapkan Tesseract + data bahasa Indonesia/Inggris untuk modul riset.
set -euo pipefail
cd "$(dirname "$0")"
command -v tesseract >/dev/null || brew install tesseract
mkdir -p tessdata
base="https://github.com/tesseract-ocr/tessdata_fast/raw/main"
for lang in ind eng osd; do
  [ -s "tessdata/$lang.traineddata" ] || curl -sSL -o "tessdata/$lang.traineddata" "$base/$lang.traineddata"
done
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
echo "Siap. Bahasa OCR: $(TESSDATA_PREFIX=$PWD/tessdata tesseract --list-langs 2>/dev/null | tail -n +2 | tr '\n' ' ')"
