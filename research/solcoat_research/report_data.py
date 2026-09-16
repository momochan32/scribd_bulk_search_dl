"""Seleksi & agregasi data untuk laporan PDF dan Excel (tanpa urusan tata letak)."""

import re
from collections import defaultdict
from dataclasses import dataclass

from .facts import Fact
from .pipeline import EquipmentRecord, FactRow, ScanResult
from .pdf_style import num

CONFIDENCE_RANK = {"tinggi": 3, "sedang": 2, "rendah": 1}
OCR_FLAG_PREFIX = "angka hasil OCR"
MIN_FACTS_TARGET = 2
MAX_SUMMARY_PARAMS = 7
COMMERCIAL_PARAMS = ("harga_energi", "konsumsi_energi_spesifik", "penghematan_energi", "konsumsi_energi_total",
                     "nilai_kalor", "konsumsi_bahan_bakar",
                     "efisiensi", "kapasitas_steam", "daya_listrik", "kapasitas_produksi")
MAX_COMMERCIAL_ROWS = 60
MAX_STRATEGIC_PER_KEYWORD = 4
MAX_STRATEGIC_ROWS = 45
MAX_VERIFY_ROWS = 90
MAX_VALUE_PARAMS = frozenset({"jumlah_burner", "jumlah_tube"})
DETAIL_TIER_B_KEYS = frozenset({"secondary_reformer", "waste_heat_boiler", "superheater"})

# Kebutuhan data Solcoat untuk kalkulasi & proposal → parameter yang memenuhinya.
SOLCOAT_NEEDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Dimensi / luas", ("luas_permukaan", "dimensi")),
    ("Refraktori", ("tebal_lining",)),
    ("Suhu firebox / keluaran", ("suhu_bridgewall", "suhu_outlet", "suhu_operasi", "suhu_tmt")),
    ("Suhu flue gas", ("suhu_flue_gas",)),
    ("Heat duty", ("heat_duty",)),
    ("Bahan bakar", ("konsumsi_bahan_bakar", "nilai_kalor")),
    ("Burner / tube", ("jumlah_burner", "jumlah_tube")),
    ("Tekanan / draft", ("tekanan", "tekanan_draft")),
)


@dataclass(frozen=True)
class EquipmentView:
    record: EquipmentRecord
    rows: tuple[FactRow, ...]
    score: float


def short_doc(name: str, width: int = 40) -> str:
    stem = re.sub(r"_\d{6,}$", "", re.sub(r"\.pdf$", "", name, flags=re.I))
    stem = re.sub(r"[-_]+", " ", stem).strip()
    return stem if len(stem) <= width else stem[: width - 1] + "…"


def source_ref(row: FactRow) -> str:
    return f"{short_doc(row.doc_name, 30)} h.{row.record.fact.page_no}"


def fmt_number(value: float) -> str:
    if value is None:
        return ""
    if abs(value) >= 100 or float(value).is_integer():
        return num(value, 0)
    return num(value, 2 if abs(value) >= 1 else 3)


STD_UNIT_LABEL = {"m2": "m²", "Nm3/jam": "Nm³/jam"}


def fmt_std(fact: Fact) -> str:
    if fact.value_std is None:
        return fact.text_value or ""
    unit = STD_UNIT_LABEL.get(fact.std_unit, fact.std_unit)
    if fact.value_max_std is not None:
        return f"{fmt_number(fact.value_std)}–{fmt_number(fact.value_max_std)} {unit}".strip()
    return f"{fmt_number(fact.value_std)} {unit}".strip()


def display_flags(fact: Fact, include_ocr: bool = False) -> list[str]:
    return [f for f in fact.flags if include_ocr or not f.startswith(OCR_FLAG_PREFIX)]


def active_documents(result: ScanResult):
    duplicates = {d.path for d in result.duplicates}
    return [a for a in result.documents if a.path not in duplicates]


def target_equipment(result: ScanResult) -> list[EquipmentView]:
    by_id: dict[str, list[FactRow]] = defaultdict(list)
    for row in result.facts:
        if row.equipment_id:
            by_id[row.equipment_id].append(row)
    views = []
    for record in result.equipment:
        rows = by_id[record.id]
        strong = [r for r in rows if CONFIDENCE_RANK[r.record.fact.confidence] >= 2]
        if record.tier not in "AB" or len(rows) < MIN_FACTS_TARGET or not strong:
            continue
        score = sum(CONFIDENCE_RANK[r.record.fact.confidence] for r in rows) * (2 if record.tier == "A" else 1)
        views.append(EquipmentView(record, tuple(sorted(rows, key=_row_sort_key)), score))
    return sorted(views, key=lambda v: (v.record.tier, v.record.company, -v.score))


def detail_equipment(views: list[EquipmentView]) -> list[EquipmentView]:
    """Detail di PDF: tier A + unit panas utama tier B. Sisanya tetap lengkap di Excel."""
    return [v for v in views if v.record.tier == "A" or v.record.key in DETAIL_TIER_B_KEYS]


def _row_sort_key(row: FactRow):
    f = row.record.fact
    return (-CONFIDENCE_RANK[f.confidence], f.category, f.param_key, row.doc_name, f.page_no)


def key_summary(view: EquipmentView) -> str:
    best: dict[str, FactRow] = {}
    for row in view.rows:
        f = row.record.fact
        if f.param_key == "atribut" or CONFIDENCE_RANK[f.confidence] < 2:
            continue
        current = best.get(f.param_key)
        if current is None or (f.param_key in MAX_VALUE_PARAMS and f.value_std > current.record.fact.value_std):
            best[f.param_key] = row
    parts = [f"{r.record.fact.param_label.split(' /')[0].split(' (')[0]}: {fmt_std(r.record.fact)}"
             for r in list(best.values())[:MAX_SUMMARY_PARAMS]]
    return "; ".join(parts) or "hanya fakta keyakinan rendah"


def coverage(view: EquipmentView) -> list[bool]:
    params = {r.record.fact.param_key for r in view.rows if CONFIDENCE_RANK[r.record.fact.confidence] >= 2}
    has_refractory = any(r.record.fact.equipment and r.record.fact.equipment.component == "Refraktori / Lining"
                         for r in view.rows)
    return [bool(params & set(keys)) or (label == "Refraktori" and has_refractory) for label, keys in SOLCOAT_NEEDS]


def commercial_rows(result: ScanResult) -> list[FactRow]:
    relevant = {a.path for a in active_documents(result) if a.relevance != "tidak relevan"}
    seen, rows = set(), []
    for row in result.facts:
        f = row.record.fact
        if row.doc_path not in relevant or f.param_key not in COMMERCIAL_PARAMS or display_flags(f):
            continue
        key = (row.record.company, f.param_key, round(f.value_std or 0, 2))
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    rows.sort(key=lambda r: (COMMERCIAL_PARAMS.index(r.record.fact.param_key), r.record.company))
    return rows[:MAX_COMMERCIAL_ROWS]


def strategic_rows(result: ScanResult) -> list[tuple[str, str, str]]:
    per_keyword: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    seen: set[str] = set()
    for analysis in sorted(active_documents(result), key=lambda a: -a.relevance_score):
        if analysis.relevance == "tidak relevan":
            continue
        for page_no, keyword, sentence in analysis.strategic:
            fingerprint = re.sub(r"\W+", "", sentence.lower())[:120]
            if fingerprint in seen or len(sentence) < 60:
                continue
            seen.add(fingerprint)
            if len(per_keyword[keyword]) < MAX_STRATEGIC_PER_KEYWORD:
                per_keyword[keyword].append((keyword, sentence, f"{short_doc(analysis.name, 30)} h.{page_no}"))
    flat = [item for items in per_keyword.values() for item in items]
    return flat[:MAX_STRATEGIC_ROWS]


def verification_rows(result: ScanResult, views: list[EquipmentView]) -> list[FactRow]:
    target_ids = {v.record.id for v in views}
    rows = [r for r in result.facts
            if (r.equipment_id in target_ids or r.record.fact.param_key in COMMERCIAL_PARAMS)
            and display_flags(r.record.fact)]
    rows.sort(key=lambda r: (not any("berbeda antar sumber" in f for f in r.record.fact.flags), r.doc_name))
    return rows[:MAX_VERIFY_ROWS]
