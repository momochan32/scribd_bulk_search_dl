"""Orkestrasi: cari PDF → deduplikasi → ekstraksi (cache + paralel) → analisis → relasi → simpan."""

import os
import sys
import threading
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import store
from .analyze import DocumentAnalysis, FactRecord, analyze_document, text_fingerprint
from .extract import DocumentText, OcrSettings, extract_document, file_sha256
from .lexicon import load_lexicon
from .validate import conflict_flags

NEAR_DUPLICATE_OVERLAP = 0.9

# Progres keseluruhan 0..1 per tahap; ekstraksi/OCR paling berat sehingga mendapat porsi terbesar.
STAGES = {
    "hash": ("Membaca daftar PDF", 0.00, 0.05),
    "extract": ("Ekstraksi teks & OCR", 0.05, 0.80),
    "analyze": ("Analisis peralatan & relasi", 0.80, 0.95),
    "save": ("Menyimpan database", 0.95, 0.97),
}
ProgressCallback = Callable[[str, float, str], None]


class ScanStopped(RuntimeError):
    """Pemindaian dihentikan pengguna; cache OCR yang sudah selesai tetap tersimpan."""
MIN_FINGERPRINT_PAGES = 3


@dataclass(frozen=True)
class ScanConfig:
    input_dir: Path
    out_dir: Path
    workers: int = max(1, (os.cpu_count() or 2) - 1)
    ocr: OcrSettings = field(default_factory=OcrSettings)
    title: str | None = None


@dataclass(frozen=True)
class EquipmentRecord:
    id: str
    company: str
    plant: str
    key: str
    label: str
    tier: str
    tag: str
    doc_names: tuple[str, ...]
    fact_count: int


@dataclass(frozen=True)
class FactRow:
    row_id: int
    doc_path: str
    doc_name: str
    doc_topic: str
    source_grade: str
    record: FactRecord
    equipment_id: str | None


@dataclass(frozen=True)
class Duplicate:
    path: str
    name: str
    original: str
    reason: str


@dataclass(frozen=True)
class ScanResult:
    config: ScanConfig
    created_at: datetime
    documents: tuple[DocumentAnalysis, ...]
    duplicates: tuple[Duplicate, ...]
    facts: tuple[FactRow, ...]
    equipment: tuple[EquipmentRecord, ...]
    db_path: Path


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def discover_pdfs(input_dir: Path, exclude: tuple[Path, ...] = ()) -> list[Path]:
    """PDF di semua subfolder, kecuali folder tersembunyi dan folder hasil (agar laporan tidak ikut dipindai)."""
    excluded = tuple(e.resolve() for e in exclude)
    return sorted(
        p for p in input_dir.rglob("*")
        if p.suffix.lower() == ".pdf"
        and not any(part.startswith(".") for part in p.relative_to(input_dir).parts)
        and not any(p.resolve().is_relative_to(e) for e in excluded)
    )


def _report(progress: ProgressCallback | None, stage: str, local_fraction: float, detail: str) -> None:
    if progress is None:
        return
    label, low, high = STAGES[stage]
    progress(label, low + (high - low) * min(max(local_fraction, 0.0), 1.0), detail)


def _check_stop(stop_event: threading.Event | None) -> None:
    if stop_event is not None and stop_event.is_set():
        raise ScanStopped("Pemindaian dihentikan pengguna")


def extract_all(paths: list[Path], conn, config: ScanConfig, log: Callable[[str], None],
                stop_event: threading.Event | None = None, progress: ProgressCallback | None = None):
    unique: dict[str, Path] = {}
    duplicates: list[Duplicate] = []
    for index, path in enumerate(paths, start=1):
        _check_stop(stop_event)
        _report(progress, "hash", index / len(paths), f"{index}/{len(paths)} file")
        sha = file_sha256(path)
        if sha in unique:
            duplicates.append(Duplicate(str(path), path.name, unique[sha].name, "file identik (SHA-256 sama)"))
        else:
            unique[sha] = path

    docs: dict[str, DocumentText] = {}
    pending = {}
    for sha, path in unique.items():
        cached = store.load_cached(conn, str(path), sha)
        if cached:
            docs[sha] = cached
        else:
            pending[sha] = path
    log(f"PDF: {len(paths)} file, {len(unique)} unik, {len(docs)} dari cache, {len(pending)} perlu diekstraksi")
    sizes = {sha: max(path.stat().st_size, 1) for sha, path in unique.items()}
    total_bytes = sum(sizes.values())
    done_bytes = sum(sizes[sha] for sha in docs)
    _report(progress, "extract", done_bytes / total_bytes, f"{len(docs)}/{len(unique)} dokumen")

    if pending:
        with ProcessPoolExecutor(max_workers=config.workers) as pool:
            futures = {pool.submit(extract_document, str(p), sha, config.ocr): sha for sha, p in pending.items()}
            for done, future in enumerate(as_completed(futures), start=1):
                if stop_event is not None and stop_event.is_set():
                    pool.shutdown(wait=False, cancel_futures=True)
                    raise ScanStopped("Pemindaian dihentikan pengguna")
                doc = future.result()
                store.save_cached(conn, doc)
                docs[doc.sha256] = doc
                done_bytes += sizes[doc.sha256]
                _report(progress, "extract", done_bytes / total_bytes, f"{len(docs)}/{len(unique)} dokumen")
                ocr = sum(p.method == "ocr" for p in doc.pages)
                log(f"  [{done}/{len(pending)}] {Path(doc.path).name[:60]} — {doc.page_count} hlm, OCR {ocr}")
    ordered = [docs[sha] for sha in unique]
    return ordered, duplicates


def find_near_duplicates(analyses: list[DocumentAnalysis]) -> tuple[list[DocumentAnalysis], list[Duplicate]]:
    kept: list[tuple[DocumentAnalysis, frozenset[int]]] = []
    duplicates: list[Duplicate] = []
    for analysis in sorted(analyses, key=lambda a: -a.page_count):
        fingerprint = text_fingerprint(analysis)
        original = next((k for k, fp in kept if len(fingerprint) >= MIN_FINGERPRINT_PAGES
                         and len(fingerprint & fp) / len(fingerprint) >= NEAR_DUPLICATE_OVERLAP), None)
        if original:
            duplicates.append(Duplicate(analysis.path, analysis.name, original.name, "isi halaman 90%+ sama"))
        else:
            kept.append((analysis, fingerprint))
    kept_paths = {a.path for a, _ in kept}
    return [a for a in analyses if a.path in kept_paths], duplicates


def _raw_equipment_id(record: FactRecord) -> str | None:
    eq = record.fact.equipment
    if eq is None:
        return None
    return "|".join((record.company, record.fact.plant or "-", eq.key, eq.tag or "-"))


def merge_untagged(ids: set[str]) -> dict[str, str]:
    """'PKT|-|primary_reformer|-' digabung ke satu-satunya versi bertag, bila tepat satu kandidat."""
    tagged = defaultdict(list)
    for eid in ids:
        company, plant, key, tag = eid.split("|")
        if tag != "-":
            tagged[(company, key)].append((plant, eid))
    mapping = {}
    for eid in ids:
        company, plant, key, tag = eid.split("|")
        if tag != "-":
            continue
        candidates = [e for p, e in tagged[(company, key)] if plant in ("-", p)]
        if len(candidates) == 1:
            mapping[eid] = candidates[0]
    return mapping


def build_fact_rows(analyses: list[DocumentAnalysis]) -> list[FactRow]:
    raw = [(a, r, _raw_equipment_id(r)) for a in analyses for r in a.facts]
    mapping = merge_untagged({eid for _, _, eid in raw if eid})
    rows = [FactRow(i, a.path, a.name, a.topic, a.source_grade, r, mapping.get(eid, eid))
            for i, (a, r, eid) in enumerate(raw, 1)]
    conflicts = conflict_flags([(row.row_id, row.equipment_id, row.doc_name, row.record.fact) for row in rows])
    return [
        replace(row, record=replace(row.record, fact=replace(
            row.record.fact, flags=row.record.fact.flags + (conflicts[row.row_id],))))
        if row.row_id in conflicts else row
        for row in rows
    ]


def build_equipment(rows: list[FactRow]) -> list[EquipmentRecord]:
    grouped: dict[str, list[FactRow]] = defaultdict(list)
    for row in rows:
        if row.equipment_id:
            grouped[row.equipment_id].append(row)
    records = []
    for eid, items in grouped.items():
        company, plant, key, tag = eid.split("|")
        eq = items[0].record.fact.equipment
        records.append(EquipmentRecord(
            id=eid, company=company, plant="" if plant == "-" else plant, key=key, label=eq.label, tier=eq.tier,
            tag="" if tag == "-" else tag, doc_names=tuple(sorted({r.doc_name for r in items})), fact_count=len(items),
        ))
    return sorted(records, key=lambda e: (e.company, e.tier, -e.fact_count))


def persist(conn, result: ScanResult) -> None:
    store.reset_results(conn)
    doc_ids = {a.path: i for i, a in enumerate(result.documents, 1)}
    dup_of = {d.path: d.original for d in result.duplicates}
    store.insert_rows(conn, "documents", [{
        "id": doc_ids[a.path], "path": a.path, "name": a.name, "topic": a.topic, "sha256": a.sha256,
        "page_count": a.page_count, "ocr_pages": a.ocr_pages, "failed_pages": a.failed_pages, "lang": a.lang,
        "source_type": a.source_type, "source_grade": a.source_grade, "companies": list(a.companies),
        "relevance": a.relevance, "relevance_score": a.relevance_score, "duplicate_of": dup_of.get(a.path),
        "error": a.error, "created_at": result.created_at.isoformat(timespec="seconds"),
        "company": a.company,
    } for a in result.documents])
    for a in result.documents:
        store.insert_rows(conn, "pages", [{"doc_id": doc_ids[a.path], "page_no": p.page_no, "method": p.method,
                                           "quality": p.quality, "lang": p.lang, "score": p.score, "text": p.text}
                                          for p in a.pages])
        store.insert_rows(conn, "pages_fts", [{"doc_name": a.name, "page_no": p.page_no, "text": p.text}
                                              for p in a.pages if p.text.strip()])
        store.insert_rows(conn, "strategic", [{"doc_id": doc_ids[a.path], "page_no": pg, "keyword": kw,
                                               "sentence": s} for pg, kw, s in a.strategic])
    store.insert_rows(conn, "equipment", [{
        "id": e.id, "company": e.company, "plant": e.plant, "key": e.key, "label": e.label, "tier": e.tier,
        "tag": e.tag, "doc_count": len(e.doc_names), "fact_count": e.fact_count} for e in result.equipment])
    store.insert_rows(conn, "facts", [_fact_row_dict(row, doc_ids[row.doc_path]) for row in result.facts])


def _fact_row_dict(row: FactRow, doc_id: int) -> dict:
    f = row.record.fact
    return {
        "id": row.row_id, "doc_id": doc_id, "page_no": f.page_no, "equipment_id": row.equipment_id,
        "component": f.equipment.component if f.equipment else None, "param_key": f.param_key,
        "param_label": f.param_label, "category": f.category, "kind": f.kind, "raw": f.raw, "value": f.value,
        "value_max": f.value_max, "unit": f.unit, "value_std": f.value_std, "value_max_std": f.value_max_std,
        "std_unit": f.std_unit, "text_value": f.text_value, "qualifier": f.qualifier, "plant": f.plant,
        "method": f.method, "confidence": f.confidence, "page_method": row.record.page_method,
        "flags": list(f.flags), "status": "belum diverifikasi", "snippet": f.snippet,
    }


def run_scan(config: ScanConfig, log: Callable[[str], None] = _log,
             stop_event: threading.Event | None = None, progress: ProgressCallback | None = None) -> ScanResult:
    lexicon = load_lexicon()
    paths = discover_pdfs(config.input_dir, exclude=(config.out_dir,))
    if not paths:
        raise FileNotFoundError(f"Tidak ada PDF di {config.input_dir}")
    db_path = config.out_dir / "research.db"
    conn = store.connect(db_path)
    try:
        docs, exact_dups = extract_all(paths, conn, config, log, stop_event, progress)
        log("Analisis teks, peralatan, dan relasi …")
        analyses = []
        for index, doc in enumerate(docs, start=1):
            _check_stop(stop_event)
            analyses.append(analyze_document(doc, config.input_dir, lexicon))
            _report(progress, "analyze", index / len(docs), f"{index}/{len(docs)} dokumen")
        kept, near_dups = find_near_duplicates(analyses)
        rows = build_fact_rows(kept)
        result = ScanResult(
            config=config, created_at=datetime.now(), documents=tuple(analyses),
            duplicates=tuple(exact_dups + near_dups), facts=tuple(rows), equipment=tuple(build_equipment(rows)),
            db_path=db_path,
        )
        _report(progress, "save", 0.0, "")
        persist(conn, result)
        _report(progress, "save", 1.0, "")
        log(f"Selesai: {len(kept)} dokumen dianalisis, {len(rows)} fakta, {len(result.equipment)} peralatan")
        return result
    finally:
        conn.close()
