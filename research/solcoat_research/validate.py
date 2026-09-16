"""Tanda (flag) untuk fakta yang perlu diverifikasi analis sebelum dipakai."""

import re
from collections import defaultdict
from dataclasses import replace

from .facts import Fact
from .lexicon import Lexicon

CONFLICT_RATIO = 1.15
CONFIDENCE_RANK = {"tinggi": 3, "sedang": 2, "rendah": 1}

# Rentang LHV wajar per bahan bakar (kcal/kg) — mengikuti aturan Project Solcoat.
FUEL_LHV_KCAL_KG = (
    (re.compile(r"(?i)fuel\s+oil|\bFO\b|minyak\s+bakar"), "fuel oil", 9700, 10000),
    (re.compile(r"(?i)\bLPG\b"), "LPG", 10900, 11100),
    (re.compile(r"(?i)gas\s+alam|natural\s+gas|\bNG\b"), "gas alam", 11000, 12000),
)


def _fmt(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def range_flags(fact: Fact, lexicon: Lexicon) -> list[str]:
    if fact.value_std is None or fact.param_key == "atribut":
        return []
    param = lexicon.param(fact.param_key)
    values = [v for v in (fact.value_std, fact.value_max_std) if v is not None]
    if all(param.low <= v <= param.high for v in values):
        return []
    return [f"di luar rentang wajar {param.label} ({_fmt(param.low)}–{_fmt(param.high)} {fact.std_unit})"]


def fuel_flags(fact: Fact) -> list[str]:
    if fact.param_key != "nilai_kalor" or fact.kind != "nilai_kalor_massa" or "LHV" not in fact.snippet.upper():
        return []
    for pattern, fuel, low, high in FUEL_LHV_KCAL_KG:
        if pattern.search(fact.snippet) and not low <= fact.value_std <= high:
            return [f"LHV {fuel} tidak wajar (harus ±{_fmt(low)}–{_fmt(high)} kcal/kg)"]
    return []


def base_flags(fact: Fact, page_method: str, lexicon: Lexicon) -> Fact:
    flags = range_flags(fact, lexicon) + fuel_flags(fact)
    if fact.is_ambiguous:
        flags.append("format angka ambigu (ribuan vs desimal)")
    if page_method == "ocr" and fact.value is not None:
        flags.append("angka hasil OCR — cocokkan dengan halaman asli")
    return replace(fact, flags=tuple(flags))


def conflict_flags(rows: list[tuple[int, str, str, Fact]]) -> dict[int, str]:
    """rows: (row_id, equipment_id, doc_name, fact). Nilai berbeda >15% untuk alat+parameter+kualifier yang sama."""
    groups: dict[tuple, list[tuple[int, str, Fact]]] = defaultdict(list)
    for row_id, equipment_id, doc_name, fact in rows:
        if not equipment_id or fact.value_std is None or CONFIDENCE_RANK[fact.confidence] < 2:
            continue
        if fact.value_max_std is not None:
            continue
        groups[(equipment_id, fact.param_key, fact.qualifier.lower())].append((row_id, doc_name, fact))

    flagged: dict[int, str] = {}
    for items in groups.values():
        docs = {doc for _, doc, _ in items}
        values = [abs(f.value_std) for _, _, f in items]
        if len(docs) < 2 or min(values) == 0 or max(values) / min(values) <= CONFLICT_RATIO:
            continue
        summary = "; ".join(sorted({f"{_fmt(f.value_std)} {f.std_unit} ({doc[:28]} h.{f.page_no})"
                                    for _, doc, f in items}))[:300]
        for row_id, _, _ in items:
            flagged[row_id] = f"nilai berbeda antar sumber: {summary}"
    return flagged
