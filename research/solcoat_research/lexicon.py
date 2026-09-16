"""Memuat lexicon.yaml menjadi pola regex siap pakai (immutable)."""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).with_name("lexicon.yaml")
_UPPER_TOKEN = re.compile(r"[A-Z0-9]{2,5}")


@dataclass(frozen=True)
class EquipmentDef:
    key: str
    label: str
    tier: str
    role: str
    pattern: re.Pattern
    exclude: re.Pattern | None


@dataclass(frozen=True)
class ParamDef:
    key: str
    label: str
    category: str
    kinds: tuple[str, ...]
    low: float
    high: float
    pattern: re.Pattern | None


@dataclass(frozen=True)
class NamedPattern:
    name: str
    kind: str
    pattern: re.Pattern


@dataclass(frozen=True)
class Lexicon:
    equipment: tuple[EquipmentDef, ...]
    parameters: tuple[ParamDef, ...]
    special: dict[str, ParamDef]
    keyword_required_kinds: frozenset[str]
    companies: tuple[NamedPattern, ...]
    plants: re.Pattern
    source_types: tuple[NamedPattern, ...]
    strategic: re.Pattern
    plant_companies: tuple[tuple[re.Pattern, str], ...] = ()

    def company_for_plant(self, plant: str) -> str:
        return next((company for pattern, company in self.plant_companies if pattern.fullmatch(plant)), "")

    def param(self, key: str) -> ParamDef:
        found = next((p for p in self.parameters if p.key == key), None)
        return found or self.special[key]


def compile_synonyms(synonyms: list[str]) -> re.Pattern:
    """Singkatan huruf besar (ID, OD, TMT) dicocokkan peka huruf besar agar 'id'/'od' biasa tidak ikut."""
    parts = []
    for syn in synonyms:
        body = syn if _UPPER_TOKEN.fullmatch(syn) else f"(?i:{syn})"
        parts.append(body)
    return re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(parts) + r")(?![A-Za-z0-9])")


def _param(key: str, raw: dict, with_pattern: bool = True) -> ParamDef:
    low, high = raw["range"]
    return ParamDef(
        key=key, label=raw["label"], category=raw["category"], kinds=tuple(raw.get("kinds", ())),
        low=float(low), high=float(high),
        pattern=compile_synonyms(raw["synonyms"]) if with_pattern else None,
    )


@lru_cache(maxsize=4)
def load_lexicon(path: Path = DEFAULT_PATH) -> Lexicon:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    equipment = tuple(
        EquipmentDef(
            key=e["key"], label=e["label"], tier=e["tier"], role=e["role"],
            pattern=compile_synonyms(e["synonyms"]),
            exclude=compile_synonyms(e["exclude"]) if e.get("exclude") else None,
        )
        for e in raw["equipment"]
    )
    return Lexicon(
        equipment=equipment,
        parameters=tuple(_param(p["key"], p) for p in raw["parameters"]),
        special={k: _param(k, v, with_pattern=False) for k, v in raw["special_parameters"].items()},
        keyword_required_kinds=frozenset(raw["keyword_required_kinds"]),
        companies=tuple(NamedPattern(c["name"], c["type"], compile_synonyms(c["synonyms"])) for c in raw["companies"]),
        plants=re.compile(
            r"(?<![A-Za-z0-9])(?:" + "|".join(pl["pattern"] for pl in raw["plants"]) + r")(?![A-Za-z0-9])", re.IGNORECASE),
        plant_companies=tuple((re.compile(pl["pattern"], re.IGNORECASE), pl["company"]) for pl in raw["plants"]),
        source_types=tuple(
            NamedPattern(s["label"], s["grade"], re.compile("|".join(s["patterns"]), re.IGNORECASE))
            for s in raw["source_types"]
        ),
        strategic=compile_synonyms(raw["strategic_keywords"]),
    )
