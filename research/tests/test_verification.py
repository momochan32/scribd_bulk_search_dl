"""Verifikasi analis: penyimpanan permanen, efek ke laporan & kalkulator, dan pratinjau halaman sumber."""

import sqlite3
from pathlib import Path

import pytest

from solcoat_research import report_data as rd
from solcoat_research.calc_prefill import load_candidates
from solcoat_research.extract import OcrSettings
from solcoat_research.pipeline import ScanConfig, run_scan
from solcoat_research.verification import (UNVERIFIED, Verification, clear_verification, fingerprint, list_facts,
                                           render_page, save_verification, validate)
from test_pipeline_e2e import _image_only_pdf, _text_pdf

PAGE = """Laporan Kerja Praktek PT Pupuk Kalimantan Timur
Unit ammonia Kaltim-3
Primary Reformer (1-H-101)
Temperatur outlet : 800 °C
Heat duty : 40 MMBtu/hr
Surface area : 463 m2
Harga gas rata-rata mencapai USD6,33 per mmbtu."""


@pytest.fixture
def scanned(tmp_path: Path):
    root = tmp_path / "src"
    (root / "Pupuk_Kaltim").mkdir(parents=True)
    _text_pdf(root / "Pupuk_Kaltim" / "KP-PKT_1.pdf", PAGE)
    config = ScanConfig(root, tmp_path / "out", workers=1, ocr=OcrSettings(enabled=False))
    return config, run_scan(config, log=lambda _: None)


def _fact(db: Path, param_key: str):
    return next(f for f in list_facts(db, include_low=True) if f.param_key == param_key)


def test_fingerprint_is_stable_and_whitespace_insensitive():
    assert fingerprint("abc", 3, "tekanan", "38  kg/cm2") == fingerprint("abc", 3, "tekanan", "38 kg/cm2")
    assert fingerprint("abc", 3, "tekanan", "38 kg/cm2") != fingerprint("abc", 4, "tekanan", "38 kg/cm2")


@pytest.mark.parametrize("verification,message", [
    (Verification("mungkin", "U"), "Status"),
    (Verification("benar", "X"), "Label"),
    (Verification("salah", "A", corrected_value=5.0), "tidak boleh punya nilai koreksi"),
])
def test_validation_rules(verification, message):
    with pytest.raises(ValueError, match=message):
        validate(verification)


def test_save_list_and_clear(scanned):
    _, result = scanned
    duty = _fact(result.db_path, "heat_duty")
    assert duty.status == UNVERIFIED and duty.doc_path.endswith("KP-PKT_1.pdf")

    saved = save_verification(result.db_path, duty, Verification("benar", "U", note=" dicek "))
    assert saved.verified_at and saved.note == "dicek"
    assert _fact(result.db_path, "heat_duty").verification.label == "U"
    assert [f.param_key for f in list_facts(result.db_path, status="benar")] == ["heat_duty"]
    assert "heat_duty" in {f.param_key for f in list_facts(result.db_path, search="MMBtu")}
    assert list_facts(result.db_path, search="tidak-ada-di-mana-pun") == []

    clear_verification(result.db_path, duty.fingerprint)
    assert _fact(result.db_path, "heat_duty").verification is None


def test_verification_survives_rescan_and_drives_report_and_calculator(scanned):
    config, result = scanned
    duty = _fact(result.db_path, "heat_duty")
    area = _fact(result.db_path, "luas_permukaan")
    save_verification(result.db_path, duty, Verification("benar", "U", corrected_value=12.5))  # MW
    save_verification(result.db_path, area, Verification("salah", "A"))

    rescanned = run_scan(config, log=lambda _: None)
    rows = {r.record.fact.param_key: r for r in rescanned.facts}
    assert rows["heat_duty"].verification.corrected_value == 12.5
    assert rows["luas_permukaan"].is_rejected

    view = next(v for v in rd.target_equipment(rescanned) if v.record.key == "primary_reformer")
    assert "luas_permukaan" not in {r.record.fact.param_key for r in view.rows}
    assert "Heat duty: 12,50 MW (koreksi)" in rd.key_summary(view)
    assert rd.confidence_label(rows["heat_duty"]) == "terverifikasi [U]"

    (candidate,) = [c for c in load_candidates(rescanned.db_path) if c.key == "primary_reformer"]
    assert candidate.known["design_duty"].value == pytest.approx(12.5 * 3.6)
    assert candidate.known["design_duty"].confidence == "terverifikasi"
    assert candidate.known["design_duty"].source.endswith("[U]")
    assert "area_total" not in candidate.known or candidate.known["area_total"].confidence == "estimasi"


def test_render_page_highlights_value(scanned):
    _, result = scanned
    duty = _fact(result.db_path, "heat_duty")
    png, found = render_page(duty.doc_path, duty.page_no, duty.raw)
    assert found and png.startswith(b"\x89PNG")


def test_render_page_on_image_only_page_reports_not_found(tmp_path: Path):
    pdf = tmp_path / "scan.pdf"
    _image_only_pdf(pdf, "Tekanan : 45 kg/cm2")
    png, found = render_page(str(pdf), 1, "45 kg/cm2")
    assert not found and png.startswith(b"\x89PNG")


def test_render_page_rejects_missing_page(tmp_path: Path):
    pdf = tmp_path / "a.pdf"
    _text_pdf(pdf, "x")
    with pytest.raises(ValueError, match="Halaman 9"):
        render_page(str(pdf), 9, "x")


def test_list_facts_without_database(tmp_path: Path):
    assert list_facts(tmp_path / "none.db") == []


def test_old_database_without_fingerprint_is_ignored_by_prefill(tmp_path: Path):
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE facts (id INTEGER)")
    assert load_candidates(db) == []
