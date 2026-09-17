"""Skor prospek dari data, bukan dari ukuran perusahaan.

Industri (kilang/petrokimia/pupuk/baja): jumlah alat berapi tier A yang punya data, harga gas (makin mahal makin
cepat payback), bukti intensitas energi, dan sinyal strategis (efisiensi energi, turnaround, dekarbonisasi).
PLTU: SOF tinggi + EAF rendah + EFOR = ruang perbaikan terbesar; CFB diberi bobot tambahan (porsi refraktori ±40%).
Bobot adalah asumsi kerja [A] — skor untuk mengurutkan, bukan angka peluang.
"""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from .pltu.pln_data import UNIT_NOTES, UNITS

WEIGHT_TIER_A = 3.0
WEIGHT_VERIFIED_FACT = 1.0
WEIGHT_STRATEGIC = 0.5
MAX_STRATEGIC_POINTS = 10.0
WEIGHT_ENERGY_INTENSITY = 3.0
GAS_PRICE_POINTS_PER_USD = 1.0
PLTU_CFB_BONUS = 10.0
STRATEGIC_KEYWORDS = ("efisiensi energi", "penghematan", "turnaround", "overhaul", "shutdown", "dekarbonisasi",
                      "nze", "net zero", "konsumsi gas", "harga gas", "boiler batubara", "coal boiler", "revamp")


@dataclass(frozen=True)
class ProspectRow:
    name: str
    score: float
    drivers: tuple[str, ...]


def _industry_row(conn, company: str) -> ProspectRow:
    tier_a = conn.execute(
        "SELECT COUNT(DISTINCT e.id) FROM equipment e JOIN facts f ON f.equipment_id = e.id "
        "LEFT JOIN verifications v ON v.fingerprint = f.fingerprint "
        "WHERE e.company = ? AND e.tier = 'A' AND COALESCE(v.status, '') != 'salah' "
        "AND (f.confidence IN ('tinggi','sedang') OR v.status = 'benar')", (company,)).fetchone()[0]
    verified = conn.execute(
        "SELECT COUNT(*) FROM facts f JOIN documents d ON d.id = f.doc_id JOIN verifications v "
        "ON v.fingerprint = f.fingerprint WHERE d.company = ? AND v.status = 'benar'", (company,)).fetchone()[0]
    sentences = [s.lower() for (s,) in conn.execute(
        "SELECT s.sentence FROM strategic s JOIN documents d ON d.id = s.doc_id "
        "WHERE d.company = ? AND d.duplicate_of IS NULL", (company,))]
    strategic = sum(any(k in s for k in STRATEGIC_KEYWORDS) for s in sentences)
    prices = [p for (p,) in conn.execute(
        "SELECT f.value_std FROM facts f JOIN documents d ON d.id = f.doc_id LEFT JOIN verifications v "
        "ON v.fingerprint = f.fingerprint WHERE d.company = ? AND f.param_key = 'harga_energi' "
        "AND f.value_std BETWEEN 2 AND 30 AND COALESCE(v.status, '') != 'salah'", (company,))]
    intensity = conn.execute(
        "SELECT COUNT(*) FROM facts f JOIN documents d ON d.id = f.doc_id WHERE d.company = ? "
        "AND f.param_key = 'konsumsi_energi_spesifik'", (company,)).fetchone()[0]

    price = max(prices) if prices else None
    parts = [(WEIGHT_TIER_A * tier_a, f"{tier_a} alat berapi tier A dengan data"),
             (WEIGHT_VERIFIED_FACT * verified, f"{verified} fakta terverifikasi"),
             (min(WEIGHT_STRATEGIC * strategic, MAX_STRATEGIC_POINTS), f"{strategic} kutipan strategis"),
             (WEIGHT_ENERGY_INTENSITY if intensity else 0.0, "data intensitas energi tersedia" if intensity else ""),
             (GAS_PRICE_POINTS_PER_USD * price if price else 0.0,
              f"harga gas hingga {price:.2f} USD/MMBtu".replace(".", ",") if price else "")]
    return ProspectRow(company, round(sum(p for p, _ in parts), 1), tuple(t for p, t in parts if p and t))


def industry_prospects(db_path: Path) -> list[ProspectRow]:
    if not Path(db_path).exists():
        return []
    with closing(sqlite3.connect(db_path)) as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
        if "company" not in columns:
            return []
        conn.execute("CREATE TABLE IF NOT EXISTS verifications (fingerprint TEXT PRIMARY KEY, status TEXT)")
        companies = [c for (c,) in conn.execute(
            "SELECT DISTINCT company FROM documents WHERE duplicate_of IS NULL AND company IS NOT NULL "
            "AND relevance != 'tidak relevan'")]
        rows = [_industry_row(conn, company) for company in companies]
    return sorted(rows, key=lambda r: -r.score)


def pltu_prospects() -> list[ProspectRow]:
    """Tabel PLN NP 2025: skor = SOF + (100 − EAF) + 0,5·EFOR, bonus CFB dari catatan unit."""
    rows = []
    for name, unit in UNITS.items():
        sof = unit.sof or 0.0
        cfb = "CFB" in UNIT_NOTES.get(name, "")
        score = sof + (100 - unit.eaf) + 0.5 * unit.efor + (PLTU_CFB_BONUS if cfb else 0.0)
        drivers = [f"SOF {sof:.2f}%".replace(".", ","), f"EAF {unit.eaf:.2f}%".replace(".", ","),
                   f"EFOR {unit.efor:.2f}%".replace(".", ",")] + (["boiler CFB"] if cfb else [])
        rows.append(ProspectRow(name, round(score, 1), tuple(drivers)))
    return sorted(rows, key=lambda r: -r.score)
