"""Penyimpanan SQLite: cache teks halaman (tahan antar-run) + tabel hasil analisis (dibangun ulang)."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .extract import EXTRACTOR_VERSION, DocumentText, PageText
from .verification import SCHEMA as VERIFICATION_SCHEMA

SCHEMA_CACHE = """
CREATE TABLE IF NOT EXISTS page_cache (
    sha256 TEXT, page_no INTEGER, version TEXT, method TEXT, quality TEXT, note TEXT, text TEXT,
    PRIMARY KEY (sha256, page_no, version));
CREATE TABLE IF NOT EXISTS doc_cache (
    sha256 TEXT, version TEXT, page_count INTEGER, error TEXT, PRIMARY KEY (sha256, version));
"""

SCHEMA_RESULTS = """
DROP TABLE IF EXISTS documents; DROP TABLE IF EXISTS pages; DROP TABLE IF EXISTS pages_fts;
DROP TABLE IF EXISTS equipment; DROP TABLE IF EXISTS facts; DROP TABLE IF EXISTS strategic;
CREATE TABLE documents (
    id INTEGER PRIMARY KEY, path TEXT, name TEXT, topic TEXT, sha256 TEXT, page_count INTEGER,
    ocr_pages INTEGER, failed_pages INTEGER, lang TEXT, source_type TEXT, source_grade TEXT, companies TEXT,
    relevance TEXT, relevance_score REAL, duplicate_of TEXT, error TEXT, created_at TEXT, company TEXT);
CREATE TABLE pages (doc_id INTEGER, page_no INTEGER, method TEXT, quality TEXT, lang TEXT, score REAL, text TEXT);
CREATE VIRTUAL TABLE pages_fts USING fts5(doc_name, page_no UNINDEXED, text, tokenize='unicode61');
CREATE TABLE equipment (
    id TEXT PRIMARY KEY, company TEXT, plant TEXT, key TEXT, label TEXT, tier TEXT, tag TEXT,
    doc_count INTEGER, fact_count INTEGER);
CREATE TABLE facts (
    id INTEGER PRIMARY KEY, doc_id INTEGER, page_no INTEGER, equipment_id TEXT, component TEXT,
    param_key TEXT, param_label TEXT, category TEXT, kind TEXT, raw TEXT, value REAL, value_max REAL,
    unit TEXT, value_std REAL, value_max_std REAL, std_unit TEXT, text_value TEXT, qualifier TEXT,
    plant TEXT, method TEXT, confidence TEXT, page_method TEXT, flags TEXT, status TEXT, snippet TEXT,
    fingerprint TEXT, label TEXT, corrected_value REAL);
CREATE TABLE strategic (doc_id INTEGER, page_no INTEGER, keyword TEXT, sentence TEXT);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_CACHE)
    conn.executescript(VERIFICATION_SCHEMA)
    return conn


def load_cached(conn: sqlite3.Connection, path: str, sha256: str) -> DocumentText | None:
    row = conn.execute("SELECT page_count, error FROM doc_cache WHERE sha256=? AND version=?",
                       (sha256, EXTRACTOR_VERSION)).fetchone()
    if row is None:
        return None
    pages = tuple(
        PageText(page_no, text, method, quality, note or "")
        for page_no, method, quality, note, text in conn.execute(
            "SELECT page_no, method, quality, note, text FROM page_cache WHERE sha256=? AND version=? ORDER BY page_no",
            (sha256, EXTRACTOR_VERSION))
    )
    return DocumentText(path, sha256, row[0], pages, row[1])


def save_cached(conn: sqlite3.Connection, doc: DocumentText) -> None:
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO page_cache VALUES (?,?,?,?,?,?,?)",
            [(doc.sha256, p.page_no, EXTRACTOR_VERSION, p.method, p.quality, p.note, p.text) for p in doc.pages],
        )
        conn.execute("INSERT OR REPLACE INTO doc_cache VALUES (?,?,?,?)",
                     (doc.sha256, EXTRACTOR_VERSION, doc.page_count, doc.error))


def reset_results(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_RESULTS)


def insert_rows(conn: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    columns = list(rows[0])
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})"
    with conn:
        conn.executemany(sql, [tuple(_sql_value(r[c]) for c in columns) for r in rows])


def _sql_value(value):
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (list, tuple, dict)) else value


def search(db_path: Path, query: str, limit: int = 20) -> list[tuple[str, int, str]]:
    with closing(sqlite3.connect(db_path)) as conn:
        return conn.execute(
            "SELECT doc_name, page_no, snippet(pages_fts, 2, '[', ']', ' … ', 18) FROM pages_fts "
            "WHERE pages_fts MATCH ? ORDER BY rank LIMIT ?", (query, limit)).fetchall()
