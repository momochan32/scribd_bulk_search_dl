"""Satu pintu untuk GUI: siapkan OCR → pindai → laporan PDF + Excel."""

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .export_xlsx import write_xlsx
from .extract import OcrSettings
from .ocr_data import ensure_tessdata
from .pipeline import ProgressCallback, ScanConfig, run_scan
from .report_pdf import build_pdf

REPORT_FOLDER_SUFFIX = "_Riset_Solcoat"


@dataclass(frozen=True)
class ResearchOutputs:
    pdf: Path
    xlsx: Path
    db: Path
    documents: int
    pages: int
    ocr_pages: int
    facts: int
    equipment_tier_a: int
    ocr_used: bool


def default_output_dir(source_dir: Path) -> Path:
    """Folder hasil di samping folder sumber, bukan di dalamnya."""
    source = Path(source_dir).expanduser().resolve()
    return source.parent / f"{source.name}{REPORT_FOLDER_SUFFIX}"


def _resolve_ocr(use_ocr: bool, log: Callable[[str], None]) -> OcrSettings:
    if not use_ocr:
        return OcrSettings(enabled=False)
    try:
        return OcrSettings(enabled=True, tessdata=str(ensure_tessdata(log)))
    except RuntimeError as exc:
        log(f"[PERINGATAN] {exc}. Pemindaian dilanjutkan tanpa OCR; halaman scan tidak akan terbaca.")
        return OcrSettings(enabled=False)


def run_research(source_dir: Path, output_dir: Path | None = None, *, use_ocr: bool = True,
                 workers: int | None = None, log: Callable[[str], None] = print,
                 stop_event: threading.Event | None = None,
                 progress: ProgressCallback | None = None) -> ResearchOutputs:
    def report(label: str, fraction: float, detail: str = "") -> None:
        if progress is not None:
            progress(label, fraction, detail)

    source = Path(source_dir).expanduser().resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Folder sumber tidak ditemukan: {source}")
    out = Path(output_dir).expanduser().resolve() if output_dir else default_output_dir(source)

    report("Menyiapkan data OCR", 0.0)
    ocr = _resolve_ocr(use_ocr, log)
    config = ScanConfig(input_dir=source, out_dir=out, ocr=ocr, **({"workers": workers} if workers else {}))
    result = run_scan(config, log=log, stop_event=stop_event, progress=progress)

    stamp = result.created_at.strftime("%Y%m%d_%H%M")
    log("Menyusun laporan PDF dan Excel …")
    report("Menyusun laporan PDF & Excel", 0.97)
    pdf = build_pdf(result, out / f"Laporan_Riset_Solcoat_{stamp}.pdf")
    xlsx = write_xlsx(result, out / f"Data_Riset_Solcoat_{stamp}.xlsx")

    report("Selesai", 1.0)
    duplicates = {d.path for d in result.duplicates}
    active = [a for a in result.documents if a.path not in duplicates]
    tier_a = {r.equipment_id for r in result.facts
              if r.equipment_id and r.record.fact.equipment.tier == "A" and r.record.fact.confidence != "rendah"}
    return ResearchOutputs(
        pdf=pdf, xlsx=xlsx, db=result.db_path, documents=len(active),
        pages=sum(a.page_count for a in active), ocr_pages=sum(a.ocr_pages for a in active),
        facts=len(result.facts), equipment_tier_a=len(tier_a), ocr_used=ocr.enabled,
    )
