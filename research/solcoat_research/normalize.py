"""Normalisasi teks hasil text layer / OCR sebelum diekstraksi."""

import re

UNICODE_LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
}

# Kata yang sering rusak karena glyph ligatur "fi"/"fl" hilang saat ekstraksi.
LIGATURE_WORDS = (
    "efisiensi", "efisien", "spesifikasi", "spesifik", "konfigurasi", "klasifikasi",
    "identifikasi", "modifikasi", "verifikasi", "sertifikasi", "sertifikat", "signifikan",
    "profil", "finansial", "fisik", "filter", "fired", "firing", "co-firing", "fluida",
    "flare", "flame", "fleksibel", "efficiency", "efficient", "specification", "specific",
    "configuration", "modification", "significant", "profile", "financial",
    "diversifikasi", "intensifikasi", "gasifikasi", "fasilitas", "reflektif",
)

_PRIVATE_USE = re.compile("[-]")
SUPERSCRIPTS = str.maketrans({"²": "2", "³": "3", "₂": "2", "₃": "3", "₄": "4", "−": "-"})

# Varian simbol derajat dari font/OCR: °, º, ᵒ, ˚, dan "o" kecil menempel angka.
_DEGREE = re.compile(r"(?<=\d)\s?(?:°|º|ᵒ|˚|o|O)\s?([CF])(?![a-zA-Z])")
_KG_CM2 = re.compile(r"kg\s?/\s?c(?:m|nr|rn)\s?(?:2|'|\?|\^2)?\s?\.?\s?([gGaA])?(?![a-zA-Z])")
_NM3 = re.compile(r"\b(N?m)\s?(?:3|'|\?|\^3)\s?/")
_M2 = re.compile(r"(?<=\d)\s?m\s?(?:\^2|\?)(?![\w/])")


def _build_ligature_repairs() -> dict[str, str]:
    repairs: dict[str, str] = {}
    for word in LIGATURE_WORDS:
        for lig in ("ffi", "ffl", "fi", "fl", "ff"):
            if lig not in word:
                continue
            for broken in (word.replace(lig, ""), word.replace(lig, lig[0])):
                if broken != word and len(broken) >= 4 and broken not in LIGATURE_WORDS:
                    repairs.setdefault(broken, word)
    return repairs


LIGATURE_REPAIRS = _build_ligature_repairs()
_LIG_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, LIGATURE_REPAIRS), key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def _match_case(template: str, word: str) -> str:
    if template.isupper():
        return word.upper()
    if template[:1].isupper():
        return word[:1].upper() + word[1:]
    return word


def repair_ligatures(text: str) -> str:
    for src, dst in UNICODE_LIGATURES.items():
        text = text.replace(src, dst)
    # Glyph ligatur dari font privat (Private Use Area) dibuang, lalu kata diperbaiki lewat kamus di bawah.
    text = _PRIVATE_USE.sub("", text)
    text = _LIG_PATTERN.sub(lambda m: _match_case(m.group(0), LIGATURE_REPAIRS[m.group(0).lower()]), text)
    return re.sub(r"(?<![A-Za-z])ue gas\b", "flue gas", text)


def normalize_units(text: str) -> str:
    text = text.translate(SUPERSCRIPTS)
    text = _DEGREE.sub(lambda m: f" °{m.group(1)}", text)
    text = _KG_CM2.sub(lambda m: "kg/cm2" + (m.group(1).lower() if m.group(1) else ""), text)
    text = _NM3.sub(lambda m: f"{m.group(1)}3/", text)
    return _M2.sub(" m2", text)


def normalize_text(text: str) -> str:
    """Perbaikan ligatur + satuan + spasi. Baris dipertahankan."""
    text = repair_ligatures(text)
    text = normalize_units(text)
    text = re.sub(r"[ \t ]+", " ", text)
    return "\n".join(line.strip() for line in text.splitlines())


def logical_lines(text: str) -> list[str]:
    """Gabungkan pecahan baris khas PDF: 'Fungsi' + ': isi' → 'Fungsi : isi'."""
    merged: list[str] = []
    for line in (ln.strip() for ln in text.splitlines()):
        if not line:
            continue
        if merged and (line.startswith(":") or merged[-1].endswith(":")):
            merged[-1] = f"{merged[-1]} {line}"
        elif merged and re.fullmatch(r"(?:\d{1,2}[.)]|[a-z][.)]|[-•])", merged[-1]):
            merged[-1] = f"{merged[-1]} {line}"
        else:
            merged.append(line)
    return merged


def flatten(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
