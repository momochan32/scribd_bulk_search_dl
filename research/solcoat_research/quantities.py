"""Menemukan besaran (angka + satuan) di dalam teks, termasuk rentang dan kualifier."""

import re
from dataclasses import dataclass

from .numparse import parse_number
from .units import Unit, match_unit

NUM = r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_QUANT = re.compile(
    r"(?P<qual>±|\+/-|\+\s|maks(?:imum|imal)?\.?|max(?:imum)?\.?|min(?:imum|imal)?\.?|<|>|≤|≥|sekitar|kurang\s+lebih)?\s*"
    r"(?:(?<=USD)|(?<=US\$)|(?<=\$)|(?<![A-Za-z0-9.,/]))"
    rf"(?P<neg>-\s?)?(?P<a>{NUM})"
    rf"(?:\s*(?:°C|°F)?\s*(?:-|–|—|s/d|sampai|hingga|to|~)\s*(?P<b>{NUM}))?"
    r"\s?",
    re.IGNORECASE,
)
QUALIFIER_MAP = {"±": "±", "+/-": "±", "+": "±", "sekitar": "±", "kurang lebih": "±", "<": "maks", "≤": "maks",
                 ">": "min", "≥": "min"}


@dataclass(frozen=True)
class Quantity:
    start: int
    end: int
    raw: str
    value: float
    value_max: float | None
    unit: Unit
    value_std: float
    value_max_std: float | None
    qualifier: str
    is_ambiguous: bool


def _qualifier(raw: str | None) -> str:
    if not raw:
        return ""
    key = re.sub(r"\s+", " ", raw.strip().lower())
    if key in QUALIFIER_MAP:
        return QUALIFIER_MAP[key]
    return "maks" if key.startswith("ma") else "min"


def _negative_allowed(text: str, neg_start: int) -> bool:
    """'-' setelah angka atau satuan adalah pemisah rentang ('400 °C - 390 °C'), bukan tanda negatif."""
    before = text[:neg_start].rstrip()
    return not before or not (before[-1].isdigit() or before[-1] in "%)" or before.endswith(("°C", "°F")))


def find_quantities(text: str, lang: str = "id") -> list[Quantity]:
    found: list[Quantity] = []
    for m in _QUANT.finditer(text):
        unit_match = match_unit(text[m.end():])
        if not unit_match:
            continue
        unit, unit_len = unit_match
        first = parse_number(m.group("a"), lang)
        second = parse_number(m.group("b"), lang) if m.group("b") else None
        if first is None:
            continue
        is_negative = bool(m.group("neg")) and _negative_allowed(text, m.start("neg"))
        value = -first.value if is_negative else first.value
        value_max = second.value if second else None
        start = m.start("neg") if is_negative else m.start("a")
        end = m.end() + unit_len
        found.append(Quantity(
            start=start,
            end=end,
            raw=text[start:end].strip(),
            value=value,
            value_max=value_max,
            unit=unit,
            value_std=unit.to_std(value),
            value_max_std=unit.to_std(value_max) if value_max is not None else None,
            qualifier=_qualifier(m.group("qual")),
            is_ambiguous=first.is_ambiguous or bool(second and second.is_ambiguous),
        ))
    return found
