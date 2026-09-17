"""Verifikasi fakta oleh analis: benar/salah, label [U]/[V]/[A], koreksi nilai, dan pratinjau halaman sumber.

Verifikasi disimpan di tabel `verifications` yang TIDAK ikut dibangun ulang saat riset diulang. Kuncinya sidik
jari (SHA-256 dokumen, halaman, parameter, teks nilai mentah) — stabil selama isi PDF tidak berubah.
"""

import hashlib
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pymupdf

STATUSES = ("benar", "salah")
LABELS = ("U", "V", "A")
LABEL_MEANING = {"U": "terukur (dokumen primer terverifikasi)", "V": "klaim vendor / prinsipal",
                 "A": "asumsi kerja"}
UNVERIFIED = "belum diverifikasi"
PREVIEW_DPI = 110
MAX_LIST_ROWS = 2000

SCHEMA = """
CREATE TABLE IF NOT EXISTS verifications (
    fingerprint TEXT PRIMARY KEY, sha256 TEXT, page_no INTEGER, param_key TEXT, raw TEXT,
    status TEXT, label TEXT, corrected_value REAL, note TEXT, verified_at TEXT);
"""


@dataclass(frozen=True)
class Verification:
    status: str
    label: str
    corrected_value: float | None = None
    note: str = ""
    verified_at: str = ""

    @property
    def is_rejected(self) -> bool:
        return self.status == "salah"

    @property
    def is_confirmed(self) -> bool:
        return self.status == "benar"


@dataclass(frozen=True)
class FactView:
    fact_id: int
    fingerprint: str
    sha256: str
    doc_name: str
    doc_path: str
    page_no: int
    equipment_id: str | None
    equipment: str
    company: str
    param_key: str
    param_label: str
    raw: str
    value_std: float | None
    std_unit: str
    qualifier: str
    confidence: str
    page_method: str
    flags: str
    snippet: str
    verification: Verification | None

    @property
    def status(self) -> str:
        return self.verification.status if self.verification else UNVERIFIED


def fingerprint(sha256: str, page_no: int, param_key: str, raw: str) -> str:
    key = "|".join((sha256, str(page_no), param_key, re.sub(r"\s+", " ", raw or "").strip()))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def validate(verification: Verification) -> None:
    if verification.status not in STATUSES:
        raise ValueError(f"Status verifikasi tidak dikenal: {verification.status}")
    if verification.label not in LABELS:
        raise ValueError(f"Label harus salah satu dari {', '.join(LABELS)}")
    if verification.is_rejected and verification.corrected_value is not None:
        raise ValueError("Fakta yang ditandai salah tidak boleh punya nilai koreksi — tandai benar lalu koreksi")


def save_verification(db_path: Path, fact: FactView, verification: Verification) -> Verification:
    validate(verification)
    stamped = Verification(verification.status, verification.label, verification.corrected_value,
                           verification.note.strip(), datetime.now().isoformat(timespec="seconds"))
    with closing(sqlite3.connect(db_path)) as conn, conn:
        ensure_schema(conn)
        conn.execute("INSERT OR REPLACE INTO verifications VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (fact.fingerprint, fact.sha256, fact.page_no, fact.param_key, fact.raw, stamped.status,
                      stamped.label, stamped.corrected_value, stamped.note, stamped.verified_at))
    return stamped


def clear_verification(db_path: Path, fingerprint_value: str) -> None:
    with closing(sqlite3.connect(db_path)) as conn, conn:
        ensure_schema(conn)
        conn.execute("DELETE FROM verifications WHERE fingerprint = ?", (fingerprint_value,))


def load_verifications(conn: sqlite3.Connection) -> dict[str, Verification]:
    ensure_schema(conn)
    return {row[0]: Verification(row[1], row[2], row[3], row[4] or "", row[5] or "")
            for row in conn.execute(
                "SELECT fingerprint, status, label, corrected_value, note, verified_at FROM verifications")}


def _row_to_view(row: sqlite3.Row, verifications: dict[str, Verification]) -> FactView:
    fp = row["fingerprint"] or fingerprint(row["sha256"], row["page_no"], row["param_key"], row["raw"])
    equipment = " ".join(p for p in (row["eq_label"], row["eq_tag"]) if p) or "-"
    return FactView(
        fact_id=row["id"], fingerprint=fp, sha256=row["sha256"], doc_name=row["doc_name"], doc_path=row["path"],
        page_no=row["page_no"], equipment_id=row["equipment_id"], equipment=equipment,
        company=row["eq_company"] or row["doc_company"] or "", param_key=row["param_key"],
        param_label=row["param_label"], raw=row["raw"] or "", value_std=row["value_std"],
        std_unit=row["std_unit"] or "", qualifier=row["qualifier"] or "", confidence=row["confidence"],
        page_method=row["page_method"] or "", flags=row["flags"] or "", snippet=row["snippet"] or "",
        verification=verifications.get(fp),
    )


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def list_facts(db_path: Path, *, equipment_id: str | None = None, target_only: bool = False,
               status: str | None = None, include_low: bool = False, search: str = "",
               limit: int = MAX_LIST_ROWS) -> list[FactView]:
    """status: None = semua, 'belum diverifikasi', 'benar', atau 'salah'."""
    if not Path(db_path).exists():
        return []
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        verifications = load_verifications(conn)
        fp_col = "f.fingerprint" if _has_column(conn, "facts", "fingerprint") else "NULL"
        company_col = "d.company" if _has_column(conn, "documents", "company") else "NULL"
        clauses, params = ["d.duplicate_of IS NULL", "f.param_key != 'atribut'"], []
        if equipment_id:
            clauses.append("f.equipment_id = ?")
            params.append(equipment_id)
        if target_only:
            clauses.append("e.tier IN ('A','B')")
        if search:
            clauses.append("(f.param_label LIKE ? OR f.raw LIKE ? OR f.snippet LIKE ? OR d.name LIKE ?)")
            params.extend([f"%{search}%"] * 4)
        rows = conn.execute(
            f"SELECT f.*, {fp_col} AS fingerprint, d.sha256, d.name AS doc_name, d.path, {company_col} AS doc_company, "
            "e.label AS eq_label, e.tag AS eq_tag, e.company AS eq_company "
            "FROM facts f JOIN documents d ON d.id = f.doc_id LEFT JOIN equipment e ON e.id = f.equipment_id "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY CASE f.confidence WHEN 'tinggi' THEN 0 WHEN 'sedang' THEN 1 ELSE 2 END, e.tier, d.name, f.page_no",
            params).fetchall()
    views = [_row_to_view(r, verifications) for r in rows]
    if not include_low:
        views = [v for v in views if v.confidence != "rendah" or v.verification is not None]
    if status:
        views = [v for v in views if v.status == status]
    return views[:limit]


def _needles(raw: str) -> list[str]:
    numbers = re.findall(r"\d[\d.,]*\d|\d", raw or "")
    return [n for n in dict.fromkeys([(raw or "").strip()] + numbers) if n]


def render_page(pdf_path: str, page_no: int, raw: str, dpi: int = PREVIEW_DPI) -> tuple[bytes, bool]:
    """PNG halaman sumber dengan nilai yang di-highlight. found=False bila teks tidak ditemukan (mis. halaman OCR)."""
    with pymupdf.open(pdf_path) as doc:
        if not 1 <= page_no <= len(doc):
            raise ValueError(f"Halaman {page_no} tidak ada di {Path(pdf_path).name}")
        page = doc[page_no - 1]
        found = False
        for needle in _needles(raw):
            hits = page.search_for(needle)
            if hits:
                for rect in hits:
                    page.add_highlight_annot(rect)
                found = True
                break
        return page.get_pixmap(dpi=dpi, annots=True).tobytes("png"), found
