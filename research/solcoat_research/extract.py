"""Ekstraksi teks per halaman: text layer bila bisa dipercaya, OCR bila kosong/rusak/berupa scan."""

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from .ocr_data import PACKAGE_TESSDATA, find_tessdata
from .text_quality import assess

EXTRACTOR_VERSION = "1"
OCR_LANG = "ind+eng"
OCR_DPI = 300
IMAGE_PAGE_MAX_CHARS = 200
IMAGE_COVERAGE_FOR_OCR = 0.5
HASH_CHUNK = 1 << 20
DEFAULT_TESSDATA = PACKAGE_TESSDATA


@dataclass(frozen=True)
class PageText:
    page_no: int
    text: str
    method: str   # text | ocr | text_rusak | kosong | gagal
    quality: str  # ok | empty | garbled
    note: str = ""


@dataclass(frozen=True)
class DocumentText:
    path: str
    sha256: str
    page_count: int
    pages: tuple[PageText, ...]
    error: str | None = None


@dataclass(frozen=True)
class OcrSettings:
    enabled: bool = True
    lang: str = OCR_LANG
    dpi: int = OCR_DPI
    tessdata: str = field(default_factory=lambda: str(find_tessdata() or DEFAULT_TESSDATA))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _image_coverage(page: pymupdf.Page) -> float:
    area = abs(page.rect) or 1.0
    covered = sum(abs(pymupdf.Rect(info["bbox"]) & page.rect) for info in page.get_image_info())
    return min(covered / area, 1.0)


def _ocr(page: pymupdf.Page, settings: OcrSettings) -> str:
    textpage = page.get_textpage_ocr(language=settings.lang, dpi=settings.dpi, full=True, tessdata=settings.tessdata)
    return page.get_text(textpage=textpage)


def _needs_ocr(page: pymupdf.Page, text: str, status: str) -> bool:
    if status in ("empty", "garbled"):
        return True
    return len(text.strip()) < IMAGE_PAGE_MAX_CHARS and _image_coverage(page) >= IMAGE_COVERAGE_FOR_OCR


def extract_page(page: pymupdf.Page, settings: OcrSettings) -> PageText:
    page_no = page.number + 1
    text = page.get_text()
    status = assess(text).status
    if not settings.enabled or not _needs_ocr(page, text, status):
        method = {"ok": "text", "empty": "kosong", "garbled": "text_rusak"}[status]
        return PageText(page_no, text if status != "garbled" else "", method, status)
    try:
        ocr_text = _ocr(page, settings)
    except Exception as exc:  # OCR gagal untuk halaman ini saja — dokumen tetap diproses
        fallback = text if status == "ok" else ""
        return PageText(page_no, fallback, "gagal", status, note=f"OCR gagal: {exc}")
    if status == "ok" and len(ocr_text.split()) <= len(text.split()):
        return PageText(page_no, text, "text", status)
    return PageText(page_no, ocr_text, "ocr", assess(ocr_text).status)


def extract_document(path: str, sha256: str, settings: OcrSettings) -> DocumentText:
    """Fungsi worker (dipanggil di proses terpisah)."""
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    pymupdf.TOOLS.mupdf_display_errors(False)
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        return DocumentText(path, sha256, 0, (), error=f"PDF tidak bisa dibuka: {exc}")
    pages: list[PageText] = []
    with doc:
        for page in doc:
            try:
                pages.append(extract_page(page, settings))
            except Exception as exc:
                pages.append(PageText(page.number + 1, "", "gagal", "empty", note=f"Halaman gagal dibaca: {exc}"))
        return DocumentText(path, sha256, len(doc), tuple(pages))
