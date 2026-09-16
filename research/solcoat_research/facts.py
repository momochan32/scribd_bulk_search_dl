"""Mengubah teks satu halaman menjadi fakta: parameter + nilai + peralatan + sumber.

Tiga lapis relasi, dari paling kuat:
  1. spesifikasi — baris 'Kunci : nilai' di bawah judul peralatan  → keyakinan tinggi
  2. kalimat     — nama peralatan disebut di kalimat yang sama     → keyakinan sedang
  3. konteks     — peralatan terakhir yang disebut di dekatnya     → keyakinan rendah
"""

import re
from dataclasses import dataclass, field

from .entities import EquipmentMention, find_equipment, find_plants, generic_heading
from .lexicon import Lexicon, ParamDef
from .normalize import flatten, logical_lines
from .quantities import Quantity, find_quantities

HEADING_MAX_CHARS = 110
HEADING_MAX_WORDS = 12
PARAM_WINDOW = 120
PREFERRED_KEYWORD_DISTANCE = 60
CONTEXT_WINDOW = 700
PARENT_WINDOW = 1500
SPEC_HEADING_MAX_LINES = 40
SNIPPET_BEFORE, SNIPPET_AFTER = 110, 60
MAX_SENTENCE_REACH = 250
IMPLICIT_HEADING_MAX_WORDS = 8
GENERIC_UNIT_KEYS = frozenset({"furnace", "boiler"})
MAX_STRATEGIC_PER_PAGE = 5

GENERIC_PARAM_BY_KIND = {
    "suhu": "suhu_operasi", "tekanan": "tekanan", "duty": "heat_duty", "luas": "luas_permukaan",
    "laju_massa": "laju_alir", "laju_volume": "laju_alir", "nilai_kalor_massa": "nilai_kalor",
    "nilai_kalor_volume": "nilai_kalor", "energi_spesifik": "konsumsi_energi_spesifik", "panjang": "dimensi",
    "daya": "daya_listrik", "persen": "efisiensi", "harga": "harga_energi",
    "kapasitas_harian": "kapasitas_produksi", "kapasitas_tahunan": "kapasitas_produksi",
    "energi": "konsumsi_energi_total",
}
ATTRIBUTE_KEYS = re.compile(
    r"(?i)^(?:tipe|type|jenis|fungsi|function|bahan\s+bakar|fuel|material|bahan|jumlah|katalis|catalyst|"
    r"lining|refrakto?ri|refractory|pabrikan|manufacturer|licensor|lisensor|kapasitas|capacity|model|konfigurasi)\b"
)
_SPEC_LINE = re.compile(
    r"^(?:[-•]\s*|\d{1,2}[.)]\s*|[a-z][.)]\s*)?(?P<key>[A-Za-z][A-Za-z0-9 /().,'&-]{1,45}?)\s*:\s*(?P<val>\S.*)$"
)
_SENTENCE_END = re.compile(r"[.;!?](?=\s+[A-Z(])")
_EQUIPMENT_START_KEY = re.compile(r"(?i)^(?:fungsi|function|kegunaan|tipe|type|kode\s+alat|nama\s+alat|no\.?\s*alat)\b")
_NUMBERING = re.compile(r"^(?:\d{1,2}[.)]?|[a-z][.)]|[-•])\s*")
_QUALIFIERS = (
    ("in/out", re.compile(r"(?i)in\s*/\s*out")),
    ("inlet", re.compile(r"(?i)\b(?:inlet|masuk(?:an)?)\b")),
    ("outlet", re.compile(r"(?i)\b(?:outlet|keluar(?:an)?|out)\b")),
    ("desain", re.compile(r"(?i)\b(?:desain|design)\b")),
    ("operasi", re.compile(r"(?i)\b(?:operasi|operating|normal)\b")),
    ("maks", re.compile(r"(?i)\b(?:maks(?:imum)?|max(?:imum)?)\b")),
    ("min", re.compile(r"(?i)\bmin(?:imum)?\b")),
)
_COUNT_PATTERNS = {
    "jumlah_tube": re.compile(
        r"(?i)(?:jumlah|number\s+of|banyak(?:nya)?)\s+(?:catalyst\s+)?(?:tubes?|pipa)\s*(?:[:=]|sebanyak|adalah|sebesar)?\s*(?P<n>\d{1,4})\b"
        r"|(?<![\d.,])(?P<n2>\d{1,4})\s*(?:buah|unit|pcs|nos)?\s+(?:catalyst\s+|katalis\s+)?(?:tubes?|pipa)\b"),
    "jumlah_burner": re.compile(
        r"(?i)(?:jumlah|number\s+of|banyak(?:nya)?)\s+(?:burners?|pembakar)\s*(?:[:=]|sebanyak|adalah|sebesar)?\s*(?P<n>\d{1,4})\b"
        r"|(?<![\d.,])(?P<n2>\d{1,4})\s*(?:buah|unit|pcs|nos)?\s+(?:burners?|pembakar)\b"),
}
_EMISSIVITY = re.compile(r"(?i)(?:emisivitas|emissivity|emisivity)\D{0,30}?(?P<v>0[.,]\d{1,3}|1[.,]0)\b")


@dataclass(frozen=True)
class Scope:
    key: str
    label: str
    tier: str
    tag: str | None
    component: str | None = None


@dataclass(frozen=True)
class Fact:
    page_no: int
    param_key: str
    param_label: str
    category: str
    kind: str
    raw: str
    value: float | None
    value_max: float | None
    unit: str
    value_std: float | None
    value_max_std: float | None
    std_unit: str
    text_value: str | None
    qualifier: str
    equipment: Scope | None
    plant: str | None
    method: str
    confidence: str
    is_ambiguous: bool
    snippet: str
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class PageFacts:
    facts: tuple[Fact, ...]
    mentions: tuple[EquipmentMention, ...]
    strategic: tuple[tuple[str, str], ...]
    last_scope: Scope | None
    last_plant: str | None


@dataclass
class _Line:
    text: str
    start: int
    heading: Scope | None = None
    spec: re.Match | None = None
    mentions: list[EquipmentMention] = field(default_factory=list)


def _scope_from_mention(m: EquipmentMention, parent: Scope | None) -> Scope:
    """Bagian/material, atau sebutan umum 'furnace'/'boiler', melekat ke unit spesifik yang sedang dibahas."""
    if m.role != "unit" and parent and parent.tier in "AB":
        return Scope(parent.key, parent.label, parent.tier, parent.tag, component=m.label)
    if m.key in GENERIC_UNIT_KEYS and parent and parent.tier == "A" and parent.key not in GENERIC_UNIT_KEYS \
            and not parent.key.startswith("lain:") and not m.tag:
        return Scope(parent.key, parent.label, parent.tier, parent.tag, component=parent.component)
    return Scope(m.key, m.label, m.tier, m.tag)


def _implicit_heading(lines: list, idx: int, lexicon_mentions) -> Scope | None:
    """'Methanator Trim Heater' + 'Fungsi : ...' → judul alat tanpa tag."""
    prev = lines[idx - 1] if idx > 0 else None
    if prev is None or prev.spec or prev.heading:
        return None
    name = _NUMBERING.sub("", prev.text).strip(" :")
    if not name or len(name.split()) > IMPLICIT_HEADING_MAX_WORDS or re.search(r"\d{2,}", name):
        return None
    if lexicon_mentions:
        m = next((x for x in lexicon_mentions if x.role == "unit"), lexicon_mentions[0])
        return Scope(m.key, m.label, m.tier, m.tag)
    return Scope(f"lain:{name.lower()}", name, "C", None)


def _heading_scope(line: _Line, current: Scope | None) -> Scope | None:
    text = line.text
    if len(text) > HEADING_MAX_CHARS or len(text.split()) > HEADING_MAX_WORDS or line.spec:
        return None
    if line.mentions:
        primary = next((m for m in line.mentions if m.role == "unit"), line.mentions[0])
        scope = _scope_from_mention(primary, current)
        generic = generic_heading(text)
        return scope if scope.tag or not generic else Scope(scope.key, scope.label, scope.tier, generic[1], scope.component)
    generic = generic_heading(text)
    if generic:
        name, tag = generic
        return Scope(f"lain:{name.lower()}", name, "C", tag)
    return None


def _build_lines(text: str, lexicon: Lexicon) -> tuple[list[_Line], str]:
    """Peralatan dideteksi pada teks gabungan agar tag yang terpotong baris ('(1-H-' + '101)') tetap terbaca."""
    lines: list[_Line] = []
    offset = 0
    for raw in logical_lines(text):
        lines.append(_Line(text=raw, start=offset, spec=_SPEC_LINE.match(raw)))
        offset += len(raw) + 1
    flat = " ".join(ln.text for ln in lines)
    for mention in find_equipment(flat, lexicon):
        owner = next((ln for ln in reversed(lines) if ln.start <= mention.start), None)
        if owner:
            owner.mentions.append(mention)
    return lines, flat


def _snippet(flat: str, start: int, end: int) -> str:
    return flatten(flat[max(0, start - SNIPPET_BEFORE):end + SNIPPET_AFTER])


def _qualifier_near(text: str) -> str:
    return next((name for name, pattern in _QUALIFIERS if pattern.search(text)), "")


def match_param(window: str, kind: str, lexicon: Lexicon) -> ParamDef | None:
    """Kata kunci paling spesifik (urutan lexicon) yang dekat dengan angka; fallback: yang terdekat."""
    candidates = []
    for order, param in enumerate(lexicon.parameters):
        if kind not in param.kinds:
            continue
        hits = list(param.pattern.finditer(window))
        if hits:
            candidates.append((len(window) - hits[-1].end(), order, param))
    if not candidates:
        return None
    near = sorted((c for c in candidates if c[0] <= PREFERRED_KEYWORD_DISTANCE), key=lambda c: c[1])
    return near[0][2] if near else min(candidates, key=lambda c: c[0])[2]


def _fact_from_quantity(q: Quantity, param: ParamDef, *, page_no, equipment, plant, method, confidence,
                        qualifier, snippet) -> Fact:
    return Fact(
        page_no=page_no, param_key=param.key, param_label=param.label, category=param.category,
        kind=q.unit.kind, raw=q.raw, value=q.value, value_max=q.value_max, unit=q.unit.key,
        value_std=q.value_std, value_max_std=q.value_max_std, std_unit=q.unit.std_unit, text_value=None,
        qualifier=qualifier or q.qualifier, equipment=equipment, plant=plant, method=method,
        confidence=confidence, is_ambiguous=q.is_ambiguous, snippet=snippet,
    )


def _plant_before(plants: list[tuple[int, str]], pos: int, fallback: str | None) -> str | None:
    before = [name for start, name in plants if start <= pos]
    return before[-1] if before else fallback


def _spec_facts(lines, flat, page_no, lang, lexicon, carry, plants, carry_plant):
    facts: list[Fact] = []
    spans: list[tuple[int, int]] = []
    current, heading_line = carry, (0 if carry else None)
    for idx, line in enumerate(lines):
        heading = _heading_scope(line, current)
        if heading:
            current, heading_line = heading, idx
            line.heading = heading
            continue
        if line.spec and _EQUIPMENT_START_KEY.match(line.spec.group("key")) and heading_line != idx - 1:
            implicit = _implicit_heading(lines, idx, lines[idx - 1].mentions if idx > 0 else [])
            if implicit:
                current, heading_line = implicit, idx - 1
                lines[idx - 1].heading = implicit
        if not line.spec or current is None:
            continue
        spans.append((line.start, line.start + len(line.text)))
        key, value = line.spec.group("key").strip(), line.spec.group("val").strip()
        confidence = "tinggi" if idx - heading_line <= SPEC_HEADING_MAX_LINES else "sedang"
        plant = _plant_before(plants, line.start, carry_plant)
        value_offset = line.start + line.spec.start("val")
        quantities = find_quantities(value, lang)
        for q in quantities:
            param = match_param(key, q.unit.kind, lexicon)
            if param is None and q.unit.kind in lexicon.keyword_required_kinds:
                continue
            param = param or lexicon.param(GENERIC_PARAM_BY_KIND[q.unit.kind])
            facts.append(_fact_from_quantity(
                q, param, page_no=page_no, equipment=current, plant=plant, method="spesifikasi",
                confidence=confidence, qualifier=key, snippet=_snippet(flat, line.start, value_offset + q.end),
            ))
        if not quantities and current.tier in "AB" and ATTRIBUTE_KEYS.match(key):
            facts.append(Fact(
                page_no=page_no, param_key="atribut", param_label=key[:40], category="atribut", kind="teks",
                raw=value[:160], value=None, value_max=None, unit="", value_std=None, value_max_std=None,
                std_unit="", text_value=value[:160], qualifier="", equipment=current, plant=plant,
                method="spesifikasi", confidence=confidence, is_ambiguous=False,
                snippet=_snippet(flat, line.start, line.start + len(line.text)),
            ))
    return facts, spans, current


def _sentence_bounds(flat: str, pos: int) -> tuple[int, int]:
    """Batas kalimat, dibatasi ±MAX_SENTENCE_REACH agar halaman tabel tanpa titik tidak jadi satu 'kalimat'."""
    floor = max(0, pos - MAX_SENTENCE_REACH)
    start = max((m.end() for m in _SENTENCE_END.finditer(flat, floor, pos)), default=floor)
    nxt = _SENTENCE_END.search(flat, pos, min(len(flat), pos + MAX_SENTENCE_REACH))
    return start, nxt.end() if nxt else min(len(flat), pos + MAX_SENTENCE_REACH)


def _scope_events(lines: list[_Line]) -> list[tuple[int, EquipmentMention | Scope]]:
    events: list[tuple[int, EquipmentMention | Scope]] = []
    for line in lines:
        if line.heading:
            events.append((line.start, line.heading))
        events.extend((m.start, m) for m in line.mentions)
    return events


def _last_unit_before(events, pos: int, window: int) -> Scope | None:
    for start, ev in reversed(events):
        if start > pos:
            continue
        if pos - start > window:
            return None
        if isinstance(ev, Scope) and ev.component is None:
            return ev
        if isinstance(ev, EquipmentMention) and ev.role == "unit":
            return Scope(ev.key, ev.label, ev.tier, ev.tag)
    return None


def _last_specific_unit_before(events, pos: int, window: int) -> Scope | None:
    for start, ev in reversed(events):
        if start > pos:
            continue
        if pos - start > window:
            return None
        scope = ev if isinstance(ev, Scope) else (
            Scope(ev.key, ev.label, ev.tier, ev.tag) if ev.role == "unit" else None)
        if scope and scope.component is None and scope.key not in GENERIC_UNIT_KEYS:
            return scope
    return None


def resolve_equipment(events, sent_start, sent_end, pos, carry) -> tuple[Scope | None, str, str]:
    in_sentence = [(start, ev) for start, ev in events
                   if sent_start <= start < sent_end and isinstance(ev, EquipmentMention)]
    if in_sentence:
        start, mention = min(in_sentence, key=lambda item: (item[0] > pos, abs(item[0] - pos)))
        needs_parent = mention.role != "unit" or mention.key in GENERIC_UNIT_KEYS
        parent = None
        if needs_parent:
            carried = carry if carry and carry.key not in GENERIC_UNIT_KEYS and not carry.key.startswith("lain:") else None
            parent = _last_specific_unit_before(events, start - 1, PARENT_WINDOW) or carried
        return _scope_from_mention(mention, parent), "kalimat", "sedang"
    context = _last_unit_before(events, pos, CONTEXT_WINDOW)
    if context:
        return context, "konteks", "rendah"
    if carry and pos < CONTEXT_WINDOW / 2:
        return carry, "konteks", "rendah"
    return None, "", ""


def _prose_facts(flat, lines, spans, page_no, lang, lexicon, carry, plants, carry_plant):
    facts: list[Fact] = []
    events = _scope_events(lines)
    for q in find_quantities(flat, lang):
        if any(s <= q.start < e for s, e in spans):
            continue
        sent_start, sent_end = _sentence_bounds(flat, q.start)
        window = flat[max(sent_start, q.start - PARAM_WINDOW):q.start]
        param = match_param(window, q.unit.kind, lexicon)
        equipment, method, confidence = resolve_equipment(events, sent_start, sent_end, q.start, carry)
        if param is None:
            if q.unit.kind in lexicon.keyword_required_kinds or equipment is None or equipment.tier == "C":
                continue
            param, confidence = lexicon.param(GENERIC_PARAM_BY_KIND[q.unit.kind]), "rendah"
        facts.append(_fact_from_quantity(
            q, param, page_no=page_no, equipment=equipment, plant=_plant_before(plants, q.start, carry_plant),
            method=method or "tanpa_alat", confidence=confidence or "rendah",
            qualifier=_qualifier_near(flat[max(sent_start, q.start - 40):q.end + 25]),
            snippet=_snippet(flat, q.start, q.end),
        ))
    return facts


def _special_facts(flat, lines, page_no, lexicon, carry, plants, carry_plant):
    facts: list[Fact] = []
    events = _scope_events(lines)
    matches = [(key, m, float(m.group("n") or m.group("n2"))) for key, pat in _COUNT_PATTERNS.items()
               for m in pat.finditer(flat)]
    matches += [("emisivitas", m, float(m.group("v").replace(",", "."))) for m in _EMISSIVITY.finditer(flat)]
    for key, m, value in matches:
        param = lexicon.param(key)
        sent_start, sent_end = _sentence_bounds(flat, m.start())
        equipment, method, confidence = resolve_equipment(events, sent_start, sent_end, m.start(), carry)
        facts.append(Fact(
            page_no=page_no, param_key=key, param_label=param.label, category=param.category,
            kind="jumlah" if key != "emisivitas" else "rasio", raw=flatten(m.group(0)), value=value,
            value_max=None, unit="", value_std=value, value_max_std=None, std_unit="",
            text_value=None, qualifier="", equipment=equipment,
            plant=_plant_before(plants, m.start(), carry_plant), method=method or "tanpa_alat",
            confidence=confidence or "rendah", is_ambiguous=False, snippet=_snippet(flat, m.start(), m.end()),
        ))
    return facts


def _strategic_snippets(flat: str, lexicon: Lexicon) -> tuple[tuple[str, str], ...]:
    found: list[tuple[str, str]] = []
    seen: set[int] = set()
    for m in lexicon.strategic.finditer(flat):
        start, end = _sentence_bounds(flat, m.start())
        if start in seen:
            continue
        seen.add(start)
        found.append((m.group(0).lower(), flatten(flat[start:end])[:320]))
        if len(found) >= MAX_STRATEGIC_PER_PAGE:
            break
    return tuple(found)


def extract_page_facts(text: str, page_no: int, lang: str, lexicon: Lexicon,
                       carry: Scope | None = None, carry_plant: str | None = None) -> PageFacts:
    lines, flat = _build_lines(text, lexicon)
    starts_with_spec = any(ln.spec for ln in lines[:3]) and not any(ln.mentions for ln in lines[:3])
    spec_carry = carry if starts_with_spec else None
    plants = find_plants(flat, lexicon)
    spec, spans, last_scope = _spec_facts(lines, flat, page_no, lang, lexicon, spec_carry, plants, carry_plant)
    prose = _prose_facts(flat, lines, spans, page_no, lang, lexicon, carry, plants, carry_plant)
    special = _special_facts(flat, lines, page_no, lexicon, carry, plants, carry_plant)
    mentions = tuple(m for ln in lines for m in ln.mentions)
    events = _scope_events(lines)
    tail_scope = _last_unit_before(events, len(flat), len(flat) + 1) or last_scope or carry
    return PageFacts(
        facts=tuple(spec + prose + special),
        mentions=mentions,
        strategic=_strategic_snippets(flat, lexicon),
        last_scope=tail_scope,
        last_plant=plants[-1][1] if plants else carry_plant,
    )
