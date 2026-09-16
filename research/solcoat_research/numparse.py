"""Parsing angka dengan format Indonesia (1.234,5) maupun Inggris (1,234.5)."""

import re
from dataclasses import dataclass

ID_WORDS = frozenset("yang dan dengan untuk pada adalah ini dari dalam akan sebagai oleh tersebut atau secara".split())
EN_WORDS = frozenset("the and of to is with for by from this that are was which as be".split())


@dataclass(frozen=True)
class ParsedNumber:
    value: float
    is_ambiguous: bool


def detect_language(text: str) -> str:
    words = re.findall(r"[a-z]+", text.lower())
    id_hits = sum(w in ID_WORDS for w in words)
    en_hits = sum(w in EN_WORDS for w in words)
    return "en" if en_hits > id_hits * 1.2 else "id"


def parse_number(raw: str, lang: str = "id") -> ParsedNumber | None:
    """Pemisah tunggal + tepat 3 digit dianggap ribuan sesuai bahasa halaman.

    Kasus yang bisa bermakna ganda (mis. '24,888' di halaman Indonesia) ditandai
    is_ambiguous agar masuk antrean verifikasi.
    """
    s = raw.strip().replace(" ", "").replace("−", "-")
    sign = -1.0 if s.startswith("-") else 1.0
    s = s.lstrip("+-")
    if not re.fullmatch(r"\d[\d.,]*", s) or s[-1] in ".,":
        return None

    has_dot, has_comma = "." in s, "," in s
    if has_dot and has_comma:
        decimal = "." if s.rfind(".") > s.rfind(",") else ","
        return _compose(s, decimal, sign, is_ambiguous=False)
    if not (has_dot or has_comma):
        return ParsedNumber(sign * float(s), False)

    sep = "." if has_dot else ","
    if s.count(sep) > 1:
        return _compose(s, None, sign, is_ambiguous=False)

    int_part, frac = s.split(sep)
    if len(frac) != 3 or int_part == "0":
        return _compose(s, sep, sign, is_ambiguous=False)

    thousands_sep = "." if lang == "id" else ","
    if sep == thousands_sep:
        return _compose(s, None, sign, is_ambiguous=False)
    return _compose(s, sep, sign, is_ambiguous=True)


def _compose(s: str, decimal: str | None, sign: float, is_ambiguous: bool) -> ParsedNumber:
    if decimal is None:
        digits = s.replace(".", "").replace(",", "")
    else:
        thousands = "," if decimal == "." else "."
        digits = s.replace(thousands, "").replace(decimal, ".")
    return ParsedNumber(sign * float(digits), is_ambiguous)
