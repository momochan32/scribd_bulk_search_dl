"""Menilai apakah text layer sebuah halaman bisa dipercaya atau perlu OCR."""

import re
from dataclasses import dataclass

from .numparse import EN_WORDS, ID_WORDS

MIN_CHARS = 60
GARBLED_TOKEN_RATIO = 0.06
MIN_COMMON_WORD_RATIO = 0.05
MIN_WORDS_FOR_RATIO = 40

COMMON_WORDS = ID_WORDS | EN_WORDS | frozenset(
    "di ke tidak juga dapat harus serta bahwa ada unit proses gas air pabrik suhu tekanan".split()
)

# Pola font rusak: huruf kecil yang diselingi angka/simbol, mis. "koe8isien", "&rilling".
_GARBLED_TOKEN = re.compile(r"[a-z][0-9&@$#;\"*<>{}|\\^~]+[a-z]|^[&@\"$#;][a-z]{2,}")
_QUOTE_RUN = re.compile(r'"{4,}')


@dataclass(frozen=True)
class TextQuality:
    status: str  # "ok" | "empty" | "garbled"
    garbled_ratio: float
    common_ratio: float


def assess(text: str) -> TextQuality:
    stripped = text.strip()
    if len(stripped) < MIN_CHARS:
        return TextQuality("empty", 0.0, 0.0)

    tokens = stripped.split()
    garbled = sum(bool(_GARBLED_TOKEN.search(tok)) for tok in tokens)
    garbled_ratio = garbled / len(tokens)
    words = re.findall(r"[a-zA-Z]+", stripped.lower())
    common_ratio = sum(w in COMMON_WORDS for w in words) / max(len(words), 1)

    if _QUOTE_RUN.search(stripped) and garbled_ratio > GARBLED_TOKEN_RATIO / 2:
        return TextQuality("garbled", garbled_ratio, common_ratio)
    if garbled_ratio > GARBLED_TOKEN_RATIO:
        return TextQuality("garbled", garbled_ratio, common_ratio)
    if len(words) >= MIN_WORDS_FOR_RATIO and common_ratio < MIN_COMMON_WORD_RATIO:
        return TextQuality("garbled", garbled_ratio, common_ratio)
    return TextQuality("ok", garbled_ratio, common_ratio)
