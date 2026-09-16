"""Tabel satuan: pola regex, jenis besaran, dan konversi ke satuan baku."""

import re
from dataclasses import dataclass
from typing import Callable

MMSCFD_TO_NM3H = 1116.3  # [A] 1 scf (60 °F) = 0,02679 Nm3 (0 °C); /24 jam


@dataclass(frozen=True)
class Unit:
    key: str
    kind: str
    std_unit: str
    to_std: Callable[[float], float]
    pattern: str


def _scale(factor: float) -> Callable[[float], float]:
    return lambda v: v * factor


# Urutan penting: pola yang lebih spesifik harus di atas pola yang lebih umum.
UNITS: tuple[Unit, ...] = (
    Unit("usd_mmbtu", "harga", "USD/MMBtu", _scale(1), r"(?:USD|US\$|\$)?\s?(?:/|per)\s?MM\s?BTU\b"),
    Unit("degC", "suhu", "°C", _scale(1), r"°C"),
    Unit("degF", "suhu", "°C", lambda v: (v - 32) * 5 / 9, r"°F"),
    Unit("kgcm2", "tekanan", "bar", _scale(0.980665), r"kg[f]?/cm2[ga]?"),
    Unit("barg", "tekanan", "bar", _scale(1), r"bar\s?[ga]?\b|barg\b|bara\b"),
    Unit("psi", "tekanan", "bar", _scale(0.0689476), r"psi[ga]?\b"),
    Unit("mpa", "tekanan", "bar", _scale(10), r"MPa\b"),
    Unit("kpa", "tekanan", "bar", _scale(0.01), r"kPa\b"),
    Unit("mmh2o", "tekanan", "bar", _scale(9.80665e-5), r"mm\s?(?:H2O|WC|wg|w\.?c\.?)\b"),
    Unit("atm", "tekanan", "bar", _scale(1.01325), r"atm\b"),
    Unit("mmbtu_h", "duty", "MW", _scale(0.29307107), r"MM\s?BTU\s?/\s?(?:h|hr|hour|jam)\b"),
    Unit("gcal_h", "duty", "MW", _scale(1.163), r"(?:Gcal|MM\s?kcal)\s?/\s?(?:h|hr|jam)\b"),
    Unit("kcal_h", "duty", "MW", _scale(1.163e-6), r"k(?:c|k)al\s?/\s?(?:h|hr|jam)\b"),
    Unit("gj_h", "duty", "MW", _scale(0.277778), r"GJ\s?/\s?(?:h|hr|jam)\b"),
    Unit("mw", "daya", "MW", _scale(1), r"MW(?:th|e)?\b"),
    Unit("kw", "daya", "MW", _scale(0.001), r"kW\b"),
    Unit("kcal_kg", "nilai_kalor_massa", "kcal/kg", _scale(1), r"k(?:c|k)al\s?/\s?kg\b"),
    Unit("kj_kg", "nilai_kalor_massa", "kcal/kg", _scale(0.238846), r"kJ\s?/\s?kg\b"),
    Unit("mj_kg", "nilai_kalor_massa", "kcal/kg", _scale(238.846), r"MJ\s?/\s?kg\b"),
    Unit("btu_lb", "nilai_kalor_massa", "kcal/kg", _scale(0.555927), r"BTU\s?/\s?lb\b"),
    Unit("kcal_nm3", "nilai_kalor_volume", "kcal/Nm3", _scale(1), r"k(?:c|k)al\s?/\s?N?m3\b"),
    Unit("btu_scf", "nilai_kalor_volume", "kcal/Nm3", _scale(9.3435), r"BTU\s?/\s?(?:scf|SCF|ft3)\b"),
    Unit("mj_nm3", "nilai_kalor_volume", "kcal/Nm3", _scale(238.846), r"MJ\s?/\s?N?m3\b"),
    Unit("mmbtu_ton", "energi_spesifik", "GJ/ton", _scale(1.055056), r"MM\s?BTU\s?/\s?(?:ton|t)\b"),
    Unit("gcal_ton", "energi_spesifik", "GJ/ton", _scale(4.1868), r"Gcal\s?/\s?(?:ton|t)\b"),
    Unit("gj_ton", "energi_spesifik", "GJ/ton", _scale(1), r"GJ\s?/\s?(?:ton|t)\b"),
    Unit("jt_mmbtu", "energi", "GJ", _scale(1.055056e6), r"(?:juta|million)\s+MM\s?BTU\b|MMMBTU\b"),
    Unit("bbtu", "energi", "GJ", _scale(1055.056), r"BBTU\b"),
    Unit("mmbtu", "energi", "GJ", _scale(1.055056), r"MM\s?BTU\b"),
    Unit("tj", "energi", "GJ", _scale(1000), r"TJ\b"),
    Unit("gj", "energi", "GJ", _scale(1), r"GJ\b"),
    Unit("nm3_h", "laju_volume", "Nm3/jam", _scale(1), r"N?m3\s?/\s?(?:jam|h|hr|hour)\b"),
    Unit("mmscfd", "laju_volume", "Nm3/jam", _scale(MMSCFD_TO_NM3H), r"MMSCF\s?/?\s?D\b|MMSCFD\b"),
    Unit("kg_h", "laju_massa", "ton/jam", _scale(0.001), r"kg\s?/\s?(?:jam|h|hr|hour)\b"),
    Unit("ton_h", "laju_massa", "ton/jam", _scale(1), r"(?:ton|t)\s?/\s?(?:jam|h|hr)\b|ton per jam\b|TPH\b"),
    Unit("ton_d", "kapasitas_harian", "ton/hari", _scale(1), r"(?:ton|t)\s?/\s?(?:hari|day|d)\b|ton per hari\b|M?TPD\b"),
    Unit("jt_ton_y", "kapasitas_tahunan", "ton/tahun", _scale(1e6),
         r"juta ton\s?(?:/|per)\s?tahun\b|juta ton\b|million (?:metric )?tons?\b|MMTPA\b"),
    Unit("ton_y", "kapasitas_tahunan", "ton/tahun", _scale(1),
         r"(?:ton|t)\s?/\s?(?:tahun|th|year|yr)\b|ton per tahun\b|M?TPY\b|MTPA\b"),
    Unit("m2", "luas", "m2", _scale(1), r"m2\b|sq\.?\s?m\b"),
    Unit("ft2", "luas", "m2", _scale(0.092903), r"ft2\b|sq\.?\s?ft\b"),
    Unit("mm", "panjang", "mm", _scale(1), r"mm\b"),
    Unit("cm", "panjang", "mm", _scale(10), r"cm\b"),
    Unit("m", "panjang", "mm", _scale(1000), r"m(?![\w/%])"),
    Unit("ft", "panjang", "mm", _scale(304.8), r"(?:ft|feet)\b"),
    Unit("inch", "panjang", "mm", _scale(25.4), r"(?:inch|inchi|in\.)(?!\w)"),
    Unit("pct", "persen", "%", _scale(1), r"%"),
)

UNIT_BY_KEY = {u.key: u for u in UNITS}
UNIT_REGEX = re.compile("|".join(f"(?P<{u.key}>{u.pattern})" for u in UNITS), re.IGNORECASE)

# Satuan yang maknanya bergantung huruf besar/kecil (MW ≠ mW, m ≠ M).
CASE_SENSITIVE_KEYS = frozenset({"mw", "kw", "m", "mpa", "kpa", "tj", "gj"})
_CASE_SENSITIVE = {k: re.compile(UNIT_BY_KEY[k].pattern) for k in CASE_SENSITIVE_KEYS}


def match_unit(text: str) -> tuple[Unit, int] | None:
    """Cocokkan satuan di awal `text`. Kembalikan (Unit, panjang cocokan)."""
    m = UNIT_REGEX.match(text)
    if not m:
        return None
    unit = UNIT_BY_KEY[m.lastgroup]
    if unit.key in CASE_SENSITIVE_KEYS and not _CASE_SENSITIVE[unit.key].match(text):
        return None
    return unit, m.end()
