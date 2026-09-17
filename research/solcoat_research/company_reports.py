"""Laporan terpisah per perusahaan — aturan segregasi: data satu klien tidak boleh muncul di materi klien lain."""

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from .export_xlsx import write_xlsx
from .extract import OcrSettings
from .pipeline import ScanConfig, ScanResult, run_scan
from .report_pdf import build_pdf

COMPANY_FOLDER = "Per_Perusahaan"


@dataclass(frozen=True)
class CompanyReport:
    company: str
    pdf: Path
    xlsx: Path
    documents: int
    facts: int


def companies_in(result: ScanResult) -> list[str]:
    duplicates = {d.path for d in result.duplicates}
    names = {a.company for a in result.documents
             if a.path not in duplicates and a.company and a.relevance != "tidak relevan"}
    return sorted(names)


def filter_result(result: ScanResult, company: str) -> ScanResult:
    """Hanya dokumen, fakta, dan peralatan milik `company`. Fakta dari dokumen perusahaan lain ikut dibuang
    walaupun menyebut nama pabrik perusahaan ini."""
    documents = tuple(a for a in result.documents if a.company == company)
    paths = {a.path for a in documents}
    facts = tuple(r for r in result.facts if r.doc_path in paths and r.record.company == company)
    equipment_ids = {r.equipment_id for r in facts if r.equipment_id}
    return replace(
        result, config=replace(result.config, title=company), documents=documents,
        duplicates=tuple(d for d in result.duplicates if d.path in paths),
        facts=facts, equipment=tuple(e for e in result.equipment if e.id in equipment_ids),
    )


def _slug(name: str) -> str:
    return re.sub(r"[^\w-]+", "_", name).strip("_")


def build_company_reports(result: ScanResult, output_dir: Path, companies: list[str] | None = None,
                          log: Callable[[str], None] = print) -> list[CompanyReport]:
    folder = Path(output_dir) / COMPANY_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    stamp = result.created_at.strftime("%Y%m%d_%H%M")
    reports = []
    for company in companies or companies_in(result):
        subset = filter_result(result, company)
        if not subset.documents:
            log(f"[LEWATI] {company}: tidak ada dokumen relevan")
            continue
        pdf = build_pdf(subset, folder / f"Laporan_Riset_{_slug(company)}_{stamp}.pdf")
        xlsx = write_xlsx(subset, folder / f"Data_Riset_{_slug(company)}_{stamp}.xlsx")
        log(f"[SUKSES] {company}: {len(subset.documents)} dokumen, {len(subset.facts)} fakta -> {pdf.name}")
        reports.append(CompanyReport(company, pdf, xlsx, len(subset.documents), len(subset.facts)))
    return reports


def run_company_reports(source_dir: Path, output_dir: Path, *, use_ocr: bool = True,
                        log: Callable[[str], None] = print) -> list[CompanyReport]:
    """Pindai ulang dari cache (cepat bila riset sudah pernah dijalankan), lalu pisahkan per perusahaan."""
    from .runner import _resolve_ocr

    config = ScanConfig(input_dir=Path(source_dir), out_dir=Path(output_dir),
                        ocr=_resolve_ocr(use_ocr, log) if use_ocr else OcrSettings(enabled=False))
    return build_company_reports(run_scan(config, log=log), output_dir, log=log)
