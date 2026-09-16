"""Deteksi peralatan (beserta tag), perusahaan, pabrik, dan jenis sumber."""

import re
from collections import Counter
from dataclasses import dataclass

from .lexicon import EquipmentDef, Lexicon
from .units import match_unit

# Tag peralatan: 1-H-101, 1-E-104 A/B, 101-B, 108-DA/B, B 1101, P 1004AB, T-2401.
TAG = (
    r"\d{1,2}\s?-\s?[A-Z]{1,3}\s?-\s?\d{2,4}(?:\s?[A-Z](?:\s?/\s?[A-Z])*)?"
    r"|\d{3,4}\s?-\s?[A-Z]{1,3}(?:\s?/\s?[A-Z])?(?![A-Za-z])"
    r"|[A-Z]{1,2}\s?-?\s?(?!19\d\d|20\d\d)\d{3,4}\s?[A-Z]{0,2}(?:\s?/\s?[A-Z])?(?![A-Za-z])"
)
_TAG_AFTER = re.compile(rf"^\s*[(\[]?\s*(?P<tag>{TAG})\s*[)\]]?")
_TAG_BEFORE = re.compile(rf"(?P<tag>{TAG})\s*[-:]?\s*$")
_NUMERIC_TAG = re.compile(r"^\s?\(?(?P<tag>(?!19\d\d|20\d\d)\d{3,4})\)?(?![\d,%\w-])(?!\.\d)")
_GENERIC_HEADING = re.compile(
    rf"^(?:\d{{1,2}}[.)]\s*|[a-z][.)]\s*|[-•]\s*)?(?P<name>[A-Za-z][\w /&.'-]{{2,60}}?)\s*\(\s*(?P<tag>{TAG})\s*\)\s*:?\s*$"
)
TAG_WINDOW = 30


@dataclass(frozen=True)
class EquipmentMention:
    start: int
    end: int
    key: str
    label: str
    tier: str
    role: str
    tag: str | None
    text: str


def _clean_tag(tag: str) -> str:
    return re.sub(r"\s*-\s*", "-", re.sub(r"\s*/\s*", "/", tag.strip()))


def _find_tag(text: str, start: int, end: int) -> str | None:
    after = _TAG_AFTER.match(text[end:end + TAG_WINDOW])
    if after:
        return _clean_tag(after.group("tag"))
    numeric = _NUMERIC_TAG.match(text[end:end + TAG_WINDOW])
    if numeric and match_unit(text[end + numeric.end():].lstrip()) is None:
        return numeric.group("tag")
    before = _TAG_BEFORE.search(text[max(0, start - 14):start])
    return _clean_tag(before.group("tag")) if before else None


def _is_excluded(defn: EquipmentDef, text: str, start: int, end: int) -> bool:
    if not defn.exclude:
        return False
    offset = max(0, start - 20)
    window = text[offset:end + 20]
    return any(m.start() + offset <= end and start <= m.end() + offset for m in defn.exclude.finditer(window))


def find_equipment(text: str, lexicon: Lexicon) -> list[EquipmentMention]:
    """Pola yang lebih spesifik didahulukan (urutan lexicon); rentang yang sudah terpakai tidak dipakai ulang."""
    taken: list[tuple[int, int]] = []
    mentions: list[EquipmentMention] = []
    for defn in lexicon.equipment:
        for m in defn.pattern.finditer(text):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            if _is_excluded(defn, text, m.start(), m.end()):
                continue
            taken.append((m.start(), m.end()))
            mentions.append(EquipmentMention(
                start=m.start(), end=m.end(), key=defn.key, label=defn.label, tier=defn.tier,
                role=defn.role, tag=_find_tag(text, m.start(), m.end()), text=m.group(0),
            ))
    return sorted(mentions, key=lambda x: x.start)


def generic_heading(line: str) -> tuple[str, str] | None:
    """'Natural gas KO drum (1-S-101)' → ('Natural gas KO drum', '1-S-101')."""
    m = _GENERIC_HEADING.match(line.strip())
    if not m:
        return None
    return m.group("name").strip(), _clean_tag(m.group("tag"))


def count_companies(text: str, lexicon: Lexicon) -> Counter:
    return Counter({c.name: n for c in lexicon.companies if (n := len(c.pattern.findall(text)))})


def normalize_plant(name: str) -> str:
    """'PABRIK-1A' / 'pabrik 1A' → 'Pabrik 1A'; 'KALTIM-5' → 'Kaltim 5'; 'unit ZA I' → 'Unit ZA I'."""
    tokens = re.split(r"[-\s]+", name.strip())
    return " ".join([tokens[0].capitalize()] + [t.upper() for t in tokens[1:]])


def find_plants(text: str, lexicon: Lexicon) -> list[tuple[int, str]]:
    return [(m.start(), normalize_plant(m.group(0))) for m in lexicon.plants.finditer(text)]


def classify_source(filename: str, first_pages_text: str, lexicon: Lexicon) -> tuple[str, str]:
    haystack = f"{filename.replace('-', ' ').replace('_', ' ')}\n{first_pages_text[:6000]}"
    for source in lexicon.source_types:
        if source.pattern.search(haystack):
            return source.name, source.kind
    return "Lainnya", "belum diketahui"
