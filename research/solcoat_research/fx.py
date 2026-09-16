"""Kurs USD→IDR hari ini, dari sumber yang sama dengan calculate.solcoat.com (frankfurter.dev).

Aturan Project Solcoat: kurs mengikuti hari dokumen dibuat dan wajib dicantumkan beserta tanggalnya.
Bila gagal diambil, kembalikan None — jangan mengarang kurs; pengguna wajib mengisi manual.
"""

import json
import urllib.request
from dataclasses import dataclass
from typing import Callable

from .ocr_data import _ssl_context

FX_URL = "https://api.frankfurter.dev/v1/latest?from=USD&to=IDR,EUR"
FX_TIMEOUT_SECONDS = 8
USER_AGENT = "MomoRescribd/1.2 (+https://github.com/momochan32/scribd_bulk_search_dl)"  # API menolak tanpa UA (403)


@dataclass(frozen=True)
class FxRate:
    usd_idr: float
    date: str
    source: str = "frankfurter.dev (ECB)"


def fetch_usd_idr(opener: Callable = urllib.request.urlopen) -> FxRate | None:
    try:
        request = urllib.request.Request(FX_URL, headers={"User-Agent": USER_AGENT})
        with opener(request, timeout=FX_TIMEOUT_SECONDS, context=_ssl_context()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        rate = float(payload["rates"]["IDR"])
        return FxRate(usd_idr=rate, date=str(payload["date"])) if rate > 0 else None
    except (OSError, ValueError, KeyError, TypeError):
        return None
