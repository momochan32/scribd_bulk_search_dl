"""Akurasi ekstraksi diukur dari verifikasi analis: presisi = benar / (benar + salah) per kelompok."""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from .verification import ensure_schema

MIN_RELIABLE_SAMPLE = 30
TARGET_GOLD_SET = 100
GROUPINGS = {"Keyakinan": "f.confidence", "Metode relasi": "f.method", "Metode halaman": "f.page_method",
             "Parameter": "f.param_label"}


@dataclass(frozen=True)
class AccuracyRow:
    grouping: str
    group: str
    verified: int
    correct: int
    wrong: int

    @property
    def precision(self) -> float | None:
        return self.correct / self.verified if self.verified else None

    @property
    def is_reliable(self) -> bool:
        return self.verified >= MIN_RELIABLE_SAMPLE


@dataclass(frozen=True)
class AccuracyReport:
    rows: tuple[AccuracyRow, ...]
    total_facts: int
    verified: int
    correct: int

    @property
    def precision(self) -> float | None:
        return self.correct / self.verified if self.verified else None

    @property
    def advice(self) -> str:
        if self.verified < TARGET_GOLD_SET:
            return (f"Baru {self.verified} fakta diverifikasi. Verifikasi minimal {TARGET_GOLD_SET} fakta acak lintas "
                    f"tingkat keyakinan agar angka akurasi bisa dipercaya (kelompok < {MIN_RELIABLE_SAMPLE} sampel "
                    "ditandai belum andal).")
        return "Sampel verifikasi sudah cukup untuk gambaran akurasi umum."


def measure(db_path: Path) -> AccuracyReport:
    if not Path(db_path).exists():
        return AccuracyReport((), 0, 0, 0)
    with closing(sqlite3.connect(db_path)) as conn:
        ensure_schema(conn)
        if not any(r[1] == "fingerprint" for r in conn.execute("PRAGMA table_info(facts)")):
            return AccuracyReport((), 0, 0, 0)
        join = "FROM facts f JOIN verifications v ON v.fingerprint = f.fingerprint WHERE f.param_key != 'atribut'"
        rows = []
        for grouping, column in GROUPINGS.items():
            for group, verified, correct in conn.execute(
                    f"SELECT {column}, COUNT(*), SUM(v.status = 'benar') {join} GROUP BY {column} ORDER BY COUNT(*) DESC"):
                rows.append(AccuracyRow(grouping, group or "-", verified, correct or 0, verified - (correct or 0)))
        total = conn.execute("SELECT COUNT(*) FROM facts WHERE param_key != 'atribut'").fetchone()[0]
        verified, correct = conn.execute(f"SELECT COUNT(*), SUM(v.status = 'benar') {join}").fetchone()
    return AccuracyReport(tuple(rows), total, verified, correct or 0)
