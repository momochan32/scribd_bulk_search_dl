"""Analisis satu dokumen: topik, perusahaan, jenis sumber, relevansi, fakta, dan konteks strategis."""

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .entities import classify_source, count_companies
from .extract import DocumentText
from .facts import Fact, extract_page_facts
from .lexicon import Lexicon
from .normalize import normalize_text
from .numparse import detect_language
from .validate import base_flags

TIER_WEIGHT = {"A": 3.0, "B": 1.0, "C": 0.0}
CONFIDENCE_WEIGHT = {"tinggi": 3.0, "sedang": 1.5, "rendah": 0.5}
STRATEGIC_WEIGHT = 0.5
RELEVANCE_LEVELS = ((60.0, "tinggi"), (15.0, "sedang"), (1.0, "rendah"))
FIRST_PAGES_FOR_SOURCE = 3
LANG_SAMPLE_CHARS = 20000


@dataclass(frozen=True)
class PageRecord:
    page_no: int
    method: str
    quality: str
    lang: str
    score: float
    text: str


@dataclass(frozen=True)
class FactRecord:
    fact: Fact
    company: str
    page_method: str


@dataclass(frozen=True)
class DocumentAnalysis:
    path: str
    name: str
    topic: str
    sha256: str
    page_count: int
    ocr_pages: int
    failed_pages: int
    lang: str
    source_type: str
    source_grade: str
    company: str
    companies: tuple[tuple[str, int], ...]
    relevance: str
    relevance_score: float
    error: str | None
    pages: tuple[PageRecord, ...]
    facts: tuple[FactRecord, ...]
    strategic: tuple[tuple[int, str, str], ...]


def topic_for(path: Path, root: Path) -> str:
    rel = path.relative_to(root)
    return rel.parts[0].replace("_", " ") if len(rel.parts) > 1 else root.name.replace("_", " ")


def resolve_company(topic: str, counts: Counter, lexicon: Lexicon) -> str:
    for company in lexicon.companies:
        if company.kind == "klien" and company.pattern.search(topic):
            return company.name
    clients = [(n, c) for c, n in counts.items()
               if next((x.kind for x in lexicon.companies if x.name == c), "") == "klien"]
    return max(clients)[1] if clients else topic


def _page_score(page_facts, strategic_count: int) -> float:
    mention_score = sum(TIER_WEIGHT[m.tier] for m in page_facts.mentions)
    fact_score = sum(CONFIDENCE_WEIGHT[f.confidence] for f in page_facts.facts
                     if f.equipment and f.equipment.tier in "AB")
    return mention_score + fact_score + STRATEGIC_WEIGHT * strategic_count


def relevance_level(score: float) -> str:
    return next((label for threshold, label in RELEVANCE_LEVELS if score >= threshold), "tidak relevan")


def _dedupe(facts: list[FactRecord]) -> list[FactRecord]:
    best: dict[tuple, FactRecord] = {}
    for record in facts:
        f = record.fact
        key = (f.page_no, f.param_key, f.value_std, f.value_max_std, f.text_value,
               f.equipment.key if f.equipment else None)
        current = best.get(key)
        if current is None or CONFIDENCE_WEIGHT[f.confidence] > CONFIDENCE_WEIGHT[current.fact.confidence]:
            best[key] = record
    return list(best.values())


def analyze_document(doc: DocumentText, root: Path, lexicon: Lexicon) -> DocumentAnalysis:
    path = Path(doc.path)
    normalized = [(p, normalize_text(p.text)) for p in doc.pages]
    full_text = "\n".join(text for _, text in normalized)
    doc_lang = detect_language(full_text[:LANG_SAMPLE_CHARS])
    counts = count_companies(full_text, lexicon)
    topic = topic_for(path, root)
    doc_company = resolve_company(topic, counts, lexicon)
    source_type, grade = classify_source(path.stem, "\n".join(t for _, t in normalized[:FIRST_PAGES_FOR_SOURCE]), lexicon)

    pages, facts, strategic = [], [], []
    carry, carry_plant = None, None
    for page, text in normalized:
        lang = detect_language(text) if len(text) > 400 else doc_lang
        result = extract_page_facts(text, page.page_no, lang, lexicon, carry, carry_plant)
        carry, carry_plant = result.last_scope, result.last_plant
        for fact in result.facts:
            company = lexicon.company_for_plant(fact.plant) if fact.plant else ""
            facts.append(FactRecord(base_flags(fact, page.method, lexicon), company or doc_company, page.method))
        strategic.extend((page.page_no, kw, sentence) for kw, sentence in result.strategic)
        pages.append(PageRecord(page.page_no, page.method, page.quality, lang,
                                _page_score(result, len(result.strategic)), text))

    score = sum(p.score for p in pages)
    return DocumentAnalysis(
        path=str(path), name=path.name, topic=topic, sha256=doc.sha256, page_count=doc.page_count,
        ocr_pages=sum(p.method == "ocr" for p in doc.pages), failed_pages=sum(p.method == "gagal" for p in doc.pages),
        lang=doc_lang, source_type=source_type, source_grade=grade, company=doc_company,
        companies=tuple(counts.most_common(6)), relevance=relevance_level(score), relevance_score=round(score, 1),
        error=doc.error, pages=tuple(pages), facts=tuple(_dedupe(facts)), strategic=tuple(strategic),
    )


def text_fingerprint(analysis: DocumentAnalysis) -> frozenset[int]:
    """Sidik jari isi untuk mendeteksi dokumen yang sama dengan nama file berbeda."""
    return frozenset(hash(re.sub(r"\W+", "", p.text.lower())) for p in analysis.pages if len(p.text) > 200)
