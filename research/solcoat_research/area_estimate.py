"""Estimasi luas hot face dari dimensi peralatan — asumsi kerja [A], bukan pengganti refractory schedule.

Silinder (furnace, sulfur furnace, kiln): selimut π·D·H, ditambah dua tutup π·D²/4 bila dipilih.
Kotak (radiant box fired heater/reformer): dinding 2·(P+L)·T, ditambah atap P·L bila dipilih; lantai opsional.
"""

import math
import re
from dataclasses import dataclass

MM_PER_M = 1000.0
PREFIX_CHARS = 40
_EXCLUDE = re.compile(r"(?i)\b(tube|tubes|pipa|pipe|nozzle|bucket|burner|katalis|catalyst|coil|manhole)\b")
_DIAMETER = re.compile(r"(?i)(?:diameter|diamater|dia\.?|\bI\.?D\b|\bO\.?D\b|Ø)\s*(?P<side>dalam|luar|inside|outside|shell)?"
                       r"[^\d:]{0,12}:?\s*$")
_HEIGHT = re.compile(r"(?i)(?:tinggi|height|panjang|length|TL\s*-\s*TL)\s*(?:shell|total)?[^\d:]{0,8}:?\s*$")
_WIDTH = re.compile(r"(?i)(?:lebar|width)[^\d:]{0,8}:?\s*$")
_SEQUENCE_QUALIFIER = re.compile(r"(?i)ID\s*x\s*TL")
INNER_SIDES = ("dalam", "inside", None, "shell")


@dataclass(frozen=True)
class AreaEstimate:
    shape: str            # silinder | kotak
    area_m2: float
    formula: str
    dimensions_mm: tuple[tuple[str, float], ...]
    sources: tuple[str, ...] = ()


def _m(value_mm: float) -> str:
    return f"{value_mm / MM_PER_M:.2f}".replace(".", ",")


def _area_text(value: float) -> str:
    return f"{value:,.1f}".replace(",", "_").replace(".", ",").replace("_", ".")


def cylinder(diameter_mm: float, height_mm: float, include_ends: bool = True, sources=()) -> AreaEstimate:
    if diameter_mm <= 0 or height_mm <= 0:
        raise ValueError("Diameter dan tinggi harus lebih dari nol")
    d, h = diameter_mm / MM_PER_M, height_mm / MM_PER_M
    shell = math.pi * d * h
    ends = 2 * math.pi * d ** 2 / 4 if include_ends else 0.0
    formula = f"π × {_m(diameter_mm)} m × {_m(height_mm)} m"
    if include_ends:
        formula += f" + 2 × π × ({_m(diameter_mm)} m)² / 4"
    total = shell + ends
    return AreaEstimate("silinder", total, f"{formula} = {_area_text(total)} m²",
                        (("diameter", diameter_mm), ("tinggi", height_mm)), tuple(sources))


def box(length_mm: float, width_mm: float, height_mm: float, include_roof: bool = True,
        include_floor: bool = False, sources=()) -> AreaEstimate:
    if min(length_mm, width_mm, height_mm) <= 0:
        raise ValueError("Panjang, lebar, dan tinggi harus lebih dari nol")
    p, l, t = (v / MM_PER_M for v in (length_mm, width_mm, height_mm))
    walls = 2 * (p + l) * t
    count = int(include_roof) + int(include_floor)
    formula = f"2 × ({_m(length_mm)} + {_m(width_mm)}) m × {_m(height_mm)} m"
    if count:
        formula += f" + {count} × {_m(length_mm)} m × {_m(width_mm)} m"
    total = walls + p * l * count
    return AreaEstimate("kotak", total, f"{formula} = {_area_text(total)} m²",
                        (("panjang", length_mm), ("lebar", width_mm), ("tinggi", height_mm)), tuple(sources))


@dataclass(frozen=True)
class DimensionFact:
    """Satu fakta dimensi (nilai sudah dalam mm) beserta kutipan dan sumbernya."""
    value_mm: float
    raw: str
    qualifier: str
    snippet: str
    page_no: int
    order: int
    source: str


def classify(fact: DimensionFact) -> tuple[str, str | None] | None:
    """('diameter', 'dalam') / ('tinggi', None) / ('lebar', None) / None dari teks tepat sebelum angka."""
    index = fact.snippet.find(fact.raw)
    tail = fact.snippet[max(0, index - PREFIX_CHARS):index] if index >= 0 else fact.qualifier
    if _EXCLUDE.search(tail):
        return None
    diameter = _DIAMETER.search(tail)
    if diameter:
        return "diameter", (diameter.group("side") or "").lower() or None
    if _HEIGHT.search(tail):
        return "tinggi", None
    if _WIDTH.search(tail):
        return "lebar", None
    return None


def _sequence_roles(facts: list[DimensionFact]) -> dict[int, str]:
    """'ID x TL-TL : 1900 mm x 4600 mm' → nilai pertama diameter, kedua tinggi."""
    groups: dict[tuple[int, str], list[DimensionFact]] = {}
    for fact in facts:
        if _SEQUENCE_QUALIFIER.search(fact.qualifier):
            groups.setdefault((fact.page_no, fact.qualifier), []).append(fact)
    roles: dict[int, str] = {}
    for group in groups.values():
        for fact, role in zip(sorted(group, key=lambda f: f.order), ("diameter", "tinggi")):
            roles[fact.order] = role
    return roles


def _group_by_page(facts: list[DimensionFact]) -> dict[int, dict[str, list[tuple[DimensionFact, str | None]]]]:
    sequence = _sequence_roles(facts)
    pages: dict[int, dict[str, list[tuple[DimensionFact, str | None]]]] = {}
    for fact in facts:
        role = (sequence[fact.order], None) if fact.order in sequence else classify(fact)
        if role is not None:
            pages.setdefault(fact.page_no, {}).setdefault(role[0], []).append((fact, role[1]))
    return pages


def estimate_from_dimensions(facts: list[DimensionFact]) -> AreaEstimate | None:
    """Halaman pertama yang lengkap: silinder bila ada diameter + tinggi, kotak bila ada lebar + dua ukuran lain."""
    pages = _group_by_page(facts)
    for page_no in sorted(pages):
        roles = pages[page_no]
        diameters = sorted(roles.get("diameter", []), key=lambda item: item[1] not in INNER_SIDES)
        heights = [f for f, _ in roles.get("tinggi", [])]
        if diameters and heights:
            d, h = diameters[0][0], max(heights, key=lambda f: f.value_mm)
            return cylinder(d.value_mm, h.value_mm, sources=tuple(dict.fromkeys((d.source, h.source))))
    for page_no in sorted(pages):
        roles = pages[page_no]
        widths = [f for f, _ in roles.get("lebar", [])]
        heights = sorted((f for f, _ in roles.get("tinggi", [])), key=lambda f: -f.value_mm)
        if widths and len(heights) >= 2:
            length, height, width = heights[0], heights[1], widths[0]
            return box(length.value_mm, width.value_mm, height.value_mm,
                       sources=tuple(dict.fromkeys((length.source, width.source, height.source))))
    return None
