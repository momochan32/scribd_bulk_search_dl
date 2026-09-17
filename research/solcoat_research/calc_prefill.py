"""Nilai yang sudah diketahui dari hasil riset (research.db) untuk mengisi form 'Hitung dengan Asumsi'."""

import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from .verification import ensure_schema

MW_TO_GJ_HR = 3.6
TON_TO_KG = 1000.0
STRONG_CONFIDENCE = ("tinggi", "sedang")
VERIFIED = "terverifikasi"
CONFIDENCE_ORDER = {VERIFIED: -1, "tinggi": 0, "sedang": 1, "rendah": 2}
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
    label = f" [{row['v_label']}]" if row["v_status"] == "benar" else ""
    return f"{doc[:40]} h.{row['page_no']}{label}"


def _confidence(row) -> str:
    return VERIFIED if row["v_status"] == "benar" else row["confidence"]


def _value_std(row) -> float | None:
    """Koreksi analis (satuan baku) menggantikan nilai hasil ekstraksi."""
    return row["v_corrected"] if row["v_corrected"] is not None else row["value_std"]


def _known(row, value, unit) -> KnownValue:
    return KnownValue(value=value, unit=unit, source=_source(row), confidence=_confidence(row), raw=row["raw"])


def _best(rows, predicate):
    matches = sorted((r for r in rows if predicate(r)), key=lambda r: (CONFIDENCE_ORDER[_confidence(r)], r["id"]))
    return matches[0] if matches else None


def _equipment_known(rows) -> dict[str, KnownValue]:
    known: dict[str, KnownValue] = {}
    duty = _best(rows, lambda r: r["param_key"] == "heat_duty" and _value_std(r))
    if duty:
        known["design_duty"] = _known(duty, _value_std(duty) * MW_TO_GJ_HR, "GJ/hr")
    fuel = _best(rows, lambda r: r["param_key"] == "konsumsi_bahan_bakar" and _value_std(r))
    if fuel and fuel["kind"] == "laju_volume":
        known["fuel_rate"] = _known(fuel, _value_std(fuel), "Nm3/hr")
    elif fuel and fuel["kind"] == "laju_massa":
        known["fuel_rate"] = _known(fuel, _value_std(fuel) * TON_TO_KG, "kg/hr")
    elif fuel and fuel["kind"] == "duty":
        known["direct_value"] = _known(fuel, _value_std(fuel) * MW_TO_GJ_HR, "GJ/hr")
    eff = _best(rows, lambda r: r["param_key"] == "efisiensi" and _value_std(r)
                and EFFICIENCY_RANGE[0] <= _value_std(r) <= EFFICIENCY_RANGE[1])
    if eff:
        known["heater_efficiency"] = _known(eff, _value_std(eff), "%")
    area = _best(rows, lambda r: r["param_key"] == "luas_permukaan" and _value_std(r)
                 and r["component"] in REFRACTORY_COMPONENTS)
    if area:
        known["area_total"] = _known(area, _value_std(area), "m2")
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
    if row["v_status"] == "benar":
        return True
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
        f"SELECT {_FACT_COLUMNS} " + _FACT_JOIN +
        "WHERE f.param_key = 'harga_energi' AND f.std_unit = 'USD/MMBtu' AND d.duplicate_of IS NULL "
        "AND d.company = ? AND COALESCE(v.status, '') != 'salah' "
        "ORDER BY v.status = 'benar' DESC, f.confidence = 'rendah', d.id DESC, f.page_no", (company,)).fetchall()
    level = next((r for r in rows if _is_price_level(r)), None)
    return _known(level, _value_std(level), "USD/MMBtu") if level else None


_FACT_COLUMNS = ("f.*, d.name AS doc_name, v.status AS v_status, v.label AS v_label, "
                 "v.corrected_value AS v_corrected")
_FACT_JOIN = ("FROM facts f JOIN documents d ON d.id = f.doc_id "
              "LEFT JOIN verifications v ON v.fingerprint = f.fingerprint ")


def load_candidates(db_path: Path) -> list[EquipmentCandidate]:
    """Peralatan tier A/B dengan minimal satu fakta keyakinan tinggi/sedang, urut tier lalu jumlah fakta."""
    if not Path(db_path).exists():
        return []
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        if not _has_column(conn, "facts", "fingerprint"):
            return []  # database dari versi lama: jalankan riset ulang (cepat, memakai cache)
        ensure_schema(conn)
        equipment = conn.execute(
            "SELECT * FROM equipment WHERE tier IN ('A','B') ORDER BY tier, fact_count DESC").fetchall()
        candidates = []
        for eq in equipment:
            rows = conn.execute(
                f"SELECT {_FACT_COLUMNS} " + _FACT_JOIN +
                "WHERE f.equipment_id = ? AND COALESCE(v.status, '') != 'salah' "
                "AND (f.confidence IN (?, ?) OR v.status = 'benar')", (eq["id"], *STRONG_CONFIDENCE)).fetchall()
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
