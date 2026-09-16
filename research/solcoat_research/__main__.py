"""CLI riset sumber PDF Solcoat.

  python -m solcoat_research scan  <folder_pdf> [--out output] [--workers 7] [--no-ocr] [--title "..."]
  python -m solcoat_research search <folder_output> "primary reformer" [--limit 20]
"""

import argparse
import sys
from pathlib import Path

from .extract import OcrSettings
from .pipeline import ScanConfig, run_scan


def _scan(args: argparse.Namespace) -> int:
    from .export_xlsx import write_xlsx
    from .report_pdf import build_pdf

    input_dir = Path(args.input).expanduser().resolve()
    if not input_dir.is_dir():
        print(f"Folder tidak ditemukan: {input_dir}", file=sys.stderr)
        return 2
    out_dir = Path(args.out).expanduser().resolve()
    config = ScanConfig(input_dir=input_dir, out_dir=out_dir, workers=args.workers,
                        ocr=OcrSettings(enabled=not args.no_ocr), title=args.title)
    result = run_scan(config)
    stamp = result.created_at.strftime("%Y%m%d_%H%M")
    pdf = build_pdf(result, out_dir / f"Laporan_Riset_Solcoat_{stamp}.pdf")
    xlsx = write_xlsx(result, out_dir / f"Data_Riset_Solcoat_{stamp}.xlsx")
    print(f"Laporan PDF : {pdf}\nData Excel  : {xlsx}\nDatabase    : {result.db_path}")
    return 0


def _search(args: argparse.Namespace) -> int:
    from .store import search

    db = Path(args.out).expanduser().resolve() / "research.db"
    if not db.exists():
        print(f"Database belum ada: {db}. Jalankan 'scan' dulu.", file=sys.stderr)
        return 2
    for doc, page, snippet in search(db, args.query, args.limit):
        print(f"{doc}  h.{page}\n    {snippet}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="solcoat_research", description="Riset sumber PDF Solcoat tanpa AI")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="Pindai folder PDF dan buat laporan")
    scan.add_argument("input", help="Folder berisi PDF (boleh bersubfolder per topik)")
    scan.add_argument("--out", default="output", help="Folder hasil (default: output)")
    scan.add_argument("--workers", type=int, default=ScanConfig.workers, help="Jumlah proses paralel")
    scan.add_argument("--no-ocr", action="store_true", help="Lewati OCR (lebih cepat, halaman scan tidak terbaca)")
    scan.add_argument("--title", help="Nama entitas di kop laporan")
    scan.set_defaults(func=_scan)
    find = sub.add_parser("search", help="Cari teks penuh di halaman yang sudah dipindai")
    find.add_argument("out", help="Folder hasil scan")
    find.add_argument("query", help="Kata kunci (sintaks FTS5, mis. \"primary reformer\" OR furnace)")
    find.add_argument("--limit", type=int, default=20)
    find.set_defaults(func=_search)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
