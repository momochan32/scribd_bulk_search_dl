"""Pembaca baris tabel datasheet (API 560 fired heater, refractory schedule) untuk dokumen klien.

Datasheet menulis satuan SEBELUM angka dan tanpa titik dua, mis.
    "Heat absorption, MMBtu/hr        45.20"   → "Heat absorption : 45.20 MMBtu/hr"
    "Bridgewall temperature (°F)      1650"    → "Bridgewall temperature : 1650 °F"
Setelah ditulis ulang, baris diproses seperti blok spesifikasi biasa (keyakinan tinggi).
⚠️ Diuji dengan contoh sintetis; cocokkan dengan datasheet klien asli sebelum dipakai rutin.
"""

import re

UNIT_ALTERNATIVES = (r"MM\s?BTU\s?/\s?hr?|Gcal\s?/\s?hr?|kcal\s?/\s?hr?|GJ\s?/\s?hr?|MW|°\s?[CF]|deg\s?[CF]|"
                     r"kg\s?/\s?cm2\s?g?|barg?|psig?|mm\s?H2O|in\.?\s?H2O|mm|m2|ft2|m|ft|in|%|Nm3\s?/\s?hr?|"
                     r"kg\s?/\s?hr?|lb\s?/\s?hr?|kcal\s?/\s?kg|BTU\s?/\s?lb|BTU\s?/\s?scf")
_ROW = re.compile(
    rf"^(?P<key>[A-Za-z][A-Za-z0-9 /&.'-]{{2,60}}?)\s*[,(\[]\s*(?P<unit>{UNIT_ALTERNATIVES})\s*[)\]]?"
    r"\s+(?P<value>-?\d[\d.,]*(?:\s*(?:-|to)\s*\d[\d.,]*)?)\s*$",
    re.IGNORECASE,
)
_DEG = re.compile(r"(?i)^deg\s?([CF])$")


def _unit(text: str) -> str:
    compact = re.sub(r"\s+", "", text)
    degree = _DEG.match(compact)
    return f"°{degree.group(1).upper()}" if degree else compact.replace("°", "°")


def normalize_datasheet(text: str) -> str:
    lines = []
    for line in text.splitlines():
        match = _ROW.match(line.strip())
        if match:
            line = f"{match.group('key').strip()} : {match.group('value').strip()} {_unit(match.group('unit'))}"
        lines.append(line)
    return "\n".join(lines)
