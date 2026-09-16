"""Nilai yang sudah diketahui dari hasil riset (research.db) untuk mengisi form 'Hitung dengan Asumsi'."""

import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

MW_TO_GJ_HR = 3.6
TON_TO_KG = 1000.0
STRONG_CONFIDENCE = ("tinggi", "sedang")
CONFIDENCE_ORDER = {"tinggi": 0, "sedang": 1}
EFFICIENCY_RANGE = (50.0, 99.0)
REFRACTORY_COMPONENTS = (None, "", "Refraktori / Lining", "Seksi Radiasi")

FUEL_HINTS = (
    ("fo", re.compile(r"(?i)fuel\s+oil|\bMFO\b|\bHSD\b|minyak\s+bakar")),
    ("lpg", re.compile(r"(?i)\bLPG\b")),
    ("refinery", re.compile(r"(?i)refinery\s+gas|off\s*gas|fuel\s+gas\s+kilang")),
    ("ng", re.compile(r"(?i)gas\s+alam|natural\s+gas|gas\s+bumi|\bNG\b")),
)
COAL_KEYS = ("coal_boiler",)


@dataclass(frozen=True)
class KnownValue:
    value: float | str
    unit: str
    source: str
    confidence: str
    raw: str


@dataclass(frozen=True)
class EquipmentCandidate:
    id: str
    company: str
    plant: str
    key: str
    label: str
    tag: str
    tier: str
    known: dict[str, KnownValue] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        head = " ".join(p for p in (self.label, self.tag) if p)
        tail = " ".join(p for p in (self.company, self.plant) if p)
        return f"{head} — {tail}" if tail else head

    @property
    def is_coal_fired(self) -> bool:
        return self.key in COAL_KEYS


def _source(row) -> str:
    doc = re.sub(r"_\d{6,}\.pdf$|\.pdf$", "", row["doc_name"], flags=re.I).replace("-", " ")
    return f"{doc[:40]} h.{row['page_no']}"


def _known(row, value, unit) -> KnownValue:
    return KnownValue(value=value, unit=unit, source=_source(row), confidence=row["confidence"], raw=row["raw"])


def _best(rows, predicate):
    matches = sorted((r for r in rows if predicate(r)), key=lambda r: (CONFIDENCE_ORDER[r["confidence"]], r["id"]))
    return matches[0] if matches else None


def _equipment_known(rows) -> dict[str, KnownValue]:
    known: dict[str, KnownValue] = {}
    duty = _best(rows, lambda r: r["param_key"] == "heat_duty" and r["value_std"])
    if duty:
        known["design_duty"] = _known(duty, duty["value_std"] * MW_TO_GJ_HR, "GJ/hr")
    fuel = _best(rows, lambda r: r["param_key"] == "konsumsi_bahan_bakar" and r["value_std"])
    if fuel and fuel["kind"] == "laju_volume":
        known["fuel_rate"] = _known(fuel, fuel["value_std"], "Nm3/hr")
    elif fuel and fuel["kind"] == "laju_massa":
        known["fuel_rate"] = _known(fuel, fuel["value_std"] * TON_TO_KG, "kg/hr")
    elif fuel and fuel["kind"] == "duty":
        known["direct_value"] = _known(fuel, fuel["value_std"] * MW_TO_GJ_HR, "GJ/hr")
    eff = _best(rows, lambda r: r["param_key"] == "efisiensi" and r["value_std"]
                and EFFICIENCY_RANGE[0] <= r["value_std"] <= EFFICIENCY_RANGE[1])
    if eff:
        known["heater_efficiency"] = _known(eff, eff["value_std"], "%")
    area = _best(rows, lambda r: r["param_key"] == "luas_permukaan" and r["value_std"]
                 and r["component"] in REFRACTORY_COMPONENTS)
    if area:
        known["area_total"] = _known(area, area["value_std"], "m2")
    fuel_type = _fuel_hint(rows)
    if fuel_type:
        known["fuel_type"] = fuel_type
    return known


def _fuel_hint(rows) -> KnownValue | None:
    for row in rows:
        if row["param_key"] not in ("atribut", "konsumsi_bahan_bakar", "nilai_kalor"):
            continue
        text = f"{row['text_value'] or ''} {row['snippet'] or ''}"
        for fuel, pattern in FUEL_HINTS:
            if pattern.search(text):
                return _known(row, fuel, "")
    return None


PLAUSIBLE_GAS_PRICE = (2.0, 30.0)  # USD/MMBtu
_DELTA_WORDS = re.compile(r"(?i)(penurunan|kenaikan|turun|naik|selisih|lebih\s+(?:rendah|tinggi)|decrease|increase)\W+(?:\w+\W+){0,3}$")


def _is_price_level(row) -> bool:
    """'harga gas turun hampir USD0,82' adalah selisih, bukan harga."""
    low, high = PLAUSIBLE_GAS_PRICE
    if not (low <= row["value_std"] <= high):
        return False
    snippet, raw = row["snippet"] or "", (row["raw"] or "").split("/")[0].split(" per")[0]
    idx = snippet.find(raw)
    before = snippet[:idx].rstrip().removesuffix("USD").removesuffix("US$").removesuffix("$") if idx >= 0 else ""
    return not _DELTA_WORDS.search(before)


def _has_column(conn, table: str, column: str) -> bool:
    return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def _company_price(conn, company: str) -> KnownValue | None:
    """Harga gas hanya dari dokumen milik perusahaan yang sama (database lama tanpa kolom company: dilewati)."""
    if not _has_column(conn, "documents", "company"):
        return None
    rows = conn.execute(
        "SELECT f.*, d.name AS doc_name FROM facts f JOIN documents d ON d.id = f.doc_id "
        "WHERE f.param_key = 'harga_energi' AND f.std_unit = 'USD/MMBtu' AND d.duplicate_of IS NULL "
        "AND d.company = ? ORDER BY f.confidence = 'rendah', d.id DESC, f.page_no", (company,)).fetchall()
    level = next((r for r in rows if _is_price_level(r)), None)
    return _known(level, level["value_std"], "USD/MMBtu") if level else None


def load_candidates(db_path: Path) -> list[EquipmentCandidate]:
    """Peralatan tier A/B dengan minimal satu fakta keyakinan tinggi/sedang, urut tier lalu jumlah fakta."""
    if not Path(db_path).exists():
        return []
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        equipment = conn.execute(
            "SELECT * FROM equipment WHERE tier IN ('A','B') ORDER BY tier, fact_count DESC").fetchall()
        candidates = []
        for eq in equipment:
            rows = conn.execute(
                "SELECT f.*, d.name AS doc_name FROM facts f JOIN documents d ON d.id = f.doc_id "
                "WHERE f.equipment_id = ? AND f.confidence IN (?, ?)", (eq["id"], *STRONG_CONFIDENCE)).fetchall()
            if not rows:
                continue
            known = _equipment_known(rows)
            price = _company_price(conn, eq["company"])
            if price:
                known["actual_price"] = price
            candidates.append(EquipmentCandidate(
                id=eq["id"], company=eq["company"], plant=eq["plant"] or "", key=eq["key"], label=eq["label"],
                tag=eq["tag"] or "", tier=eq["tier"], known=known))
    return candidates
