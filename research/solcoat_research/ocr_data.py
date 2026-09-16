"""Lokasi & unduhan data bahasa OCR.

Mesin OCR sudah tertanam di PyMuPDF; yang dibutuhkan hanya file *.traineddata. Karena itu aplikasi
yang dibagikan ke rekan tidak perlu memasang Tesseract — data bahasa diunduh sekali ke folder pengguna.
"""

import os
import ssl
import sys
import urllib.request
from pathlib import Path
from typing import Callable

REQUIRED_LANGS = ("ind", "eng")
TESSDATA_URL = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/{lang}.traineddata"
MIN_TRAINEDDATA_BYTES = 500_000
DOWNLOAD_TIMEOUT_SECONDS = 60
PACKAGE_TESSDATA = Path(__file__).resolve().parent.parent / "tessdata"


def user_tessdata_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MomoRescribd"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "MomoRescribd"
    else:
        base = Path.home() / ".local" / "share" / "momo-rescribd"
    return base / "tessdata"


def _candidates() -> list[Path]:
    env = os.environ.get("TESSDATA_PREFIX")
    return [Path(p) for p in (
        env, PACKAGE_TESSDATA, user_tessdata_dir(), "/opt/homebrew/share/tessdata", "/usr/local/share/tessdata",
        "/usr/share/tesseract-ocr/5/tessdata", "/usr/share/tesseract-ocr/4.00/tessdata",
    ) if p]


def is_complete(folder: Path) -> bool:
    return all((folder / f"{lang}.traineddata").is_file()
               and (folder / f"{lang}.traineddata").stat().st_size >= MIN_TRAINEDDATA_BYTES
               for lang in REQUIRED_LANGS)


def find_tessdata() -> Path | None:
    return next((folder for folder in _candidates() if is_complete(folder)), None)


def _ssl_context() -> ssl.SSLContext:
    """Aplikasi beku (PyInstaller) di macOS sering tidak menemukan sertifikat sistem; pakai certifi bila ada."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def download_tessdata(dest: Path | None = None, log: Callable[[str], None] = lambda _: None,
                      opener: Callable = urllib.request.urlopen) -> Path:
    """Unduh data bahasa yang belum ada. File ditulis ke .part lalu di-rename agar unduhan terputus tidak dipakai."""
    folder = dest or user_tessdata_dir()
    folder.mkdir(parents=True, exist_ok=True)
    context = _ssl_context()
    for lang in REQUIRED_LANGS:
        target = folder / f"{lang}.traineddata"
        if target.is_file() and target.stat().st_size >= MIN_TRAINEDDATA_BYTES:
            continue
        log(f"Mengunduh data OCR bahasa '{lang}' …")
        partial = target.with_suffix(".part")
        try:
            with opener(TESSDATA_URL.format(lang=lang), timeout=DOWNLOAD_TIMEOUT_SECONDS, context=context) as resp:
                partial.write_bytes(resp.read())
        except OSError as exc:
            partial.unlink(missing_ok=True)
            raise RuntimeError(f"Gagal mengunduh data OCR '{lang}': {exc}") from exc
        if partial.stat().st_size < MIN_TRAINEDDATA_BYTES:
            partial.unlink(missing_ok=True)
            raise RuntimeError(f"Data OCR '{lang}' yang diunduh tidak lengkap")
        partial.replace(target)
    return folder


def ensure_tessdata(log: Callable[[str], None] = lambda _: None) -> Path:
    return find_tessdata() or download_tessdata(log=log)
