"""Analisis Lanjutan: NPV degradasi ε, akurasi, prospek, laporan per perusahaan, dokumen klien, kamus kilang/baja."""

from pathlib import Path

import pymupdf
import pytest

from solcoat_research.accuracy import measure
from solcoat_research.company_reports import build_company_reports, companies_in, filter_result
from solcoat_research.datasheet import normalize_datasheet
from solcoat_research.entities import find_equipment
from solcoat_research.extract import OcrSettings
from solcoat_research.lexicon import load_lexicon
from solcoat_research.npv import NpvInputs, calculate_npv, emissivity_at, validate
from solcoat_research.pipeline import ScanConfig, run_scan
from solcoat_research.prospect import industry_prospects, pltu_prospects
from solcoat_research.runner import default_output_dir, run_research
from solcoat_research.verification import Verification, list_facts, save_verification
from test_pipeline_e2e import _text_pdf

PKT = """Laporan Kerja Praktek PT Pupuk Kalimantan Timur
Unit ammonia Kaltim-3
Primary Reformer (1-H-101)
Temperatur outlet : 800 °C
Tekanan : 38 kg/cm2
Program efisiensi energi dan turnaround pabrik amoniak dijalankan.
Harga gas rata-rata mencapai USD6,33 per mmbtu."""
PG = """Laporan Kerja Praktek PT Petrokimia Gresik
Sulphur furnace (B 1101)
Temperatur : 1050 °C
Tekanan : 0,5 kg/cm2"""


@pytest.fixture
def scanned(tmp_path: Path):
    root = tmp_path / "src"
    (root / "Pupuk_Kaltim").mkdir(parents=True)
    (root / "Petrokimia_Gresik").mkdir()
    _text_pdf(root / "Pupuk_Kaltim" / "KP-PKT_1.pdf", PKT)
    _text_pdf(root / "Petrokimia_Gresik" / "KP-PG_2.pdf", PG)
    return run_scan(ScanConfig(root, tmp_path / "out", workers=1, ocr=OcrSettings(enabled=False)), log=lambda _: None)


class TestNpv:
    def test_emissivity_declines_linearly_then_holds(self):
        inp = NpvInputs(1e9, 5e8, eps_initial=0.98, eps_end=0.80, degradation_years=7)
        assert emissivity_at(inp, 0) == pytest.approx(0.98)
        assert emissivity_at(inp, 3.5) == pytest.approx(0.89)
        assert emissivity_at(inp, 20) == pytest.approx(0.80)

    def test_degradation_reduces_npv_and_payback_is_found(self):
        result = calculate_npv(NpvInputs(1e9, 5e8, discount_rate_pct=10, years=10))
        assert result.npv < result.npv_without_degradation
        assert result.rows[-1].factor == pytest.approx((0.80 - 0.55) / (0.98 - 0.55))
        assert 2 < result.discounted_payback_years < 4
        assert 0.2 < result.irr < 0.6

    def test_never_pays_back(self):
        result = calculate_npv(NpvInputs(1e10, 1e8, years=5))
        assert result.discounted_payback_years is None and result.npv < 0

    @pytest.mark.parametrize("bad", [NpvInputs(0, 1), NpvInputs(1, 1, years=0),
                                     NpvInputs(1, 1, eps_end=0.5, eps_substrate=0.55)])
    def test_validation(self, bad):
        with pytest.raises(ValueError):
            validate(bad)


class TestAccuracyAndProspects:
    def test_accuracy_from_verifications(self, scanned):
        assert measure(scanned.db_path).verified == 0
        facts = list_facts(scanned.db_path, include_low=True)
        save_verification(scanned.db_path, facts[0], Verification("benar", "U"))
        save_verification(scanned.db_path, facts[1], Verification("salah", "A"))
        report = measure(scanned.db_path)
        assert (report.verified, report.correct, report.precision) == (2, 1, 0.5)
        assert "Verifikasi minimal 100" in report.advice
        assert any(r.grouping == "Keyakinan" and not r.is_reliable for r in report.rows)

    def test_industry_prospects_rank_company_with_more_signals(self, scanned):
        rows = industry_prospects(scanned.db_path)
        assert [r.name for r in rows][0] == "Pupuk Kalimantan Timur"
        assert any("harga gas hingga 6,33" in d for d in rows[0].drivers)

    def test_pltu_prospects_follow_sof_eaf_not_size(self):
        names = [r.name for r in pltu_prospects()]
        assert names.index("UP Nagan Raya") < names.index("UP Paiton")
        assert names.index("UP Tarahan") < names.index("UP Paiton")


class TestCompanyReports:
    def test_filter_keeps_only_that_company(self, scanned):
        assert companies_in(scanned) == ["Petrokimia Gresik", "Pupuk Kalimantan Timur"]
        subset = filter_result(scanned, "Petrokimia Gresik")
        assert {a.company for a in subset.documents} == {"Petrokimia Gresik"}
        assert {r.record.company for r in subset.facts} == {"Petrokimia Gresik"}
        assert all(e.company == "Petrokimia Gresik" for e in subset.equipment)

    def test_reports_do_not_leak_other_company(self, scanned, tmp_path: Path):
        reports = build_company_reports(scanned, tmp_path / "out", log=lambda _: None)
        pg = next(r for r in reports if r.company == "Petrokimia Gresik")
        text = "".join(p.get_text() for p in pymupdf.open(pg.pdf))
        assert "B 1101" in text and "Kaltim" not in text and "1-H-101" not in text
        assert pg.pdf.parent.name == "Per_Perusahaan"


class TestClientDocuments:
    def test_datasheet_rows_are_rewritten(self):
        text = "Heat absorption, MMBtu/hr        45.20\nBridgewall temperature (deg F)   1650\nNotes: none"
        assert normalize_datasheet(text).splitlines() == [
            "Heat absorption : 45.20 MMBtu/hr", "Bridgewall temperature : 1650 °F", "Notes: none"]

    def test_client_scan_reads_api560_style_sheet(self, tmp_path: Path):
        root = tmp_path / "Klien_X"
        (root / "Pertamina").mkdir(parents=True)
        _text_pdf(root / "Pertamina" / "datasheet.pdf",
                  "FIRED HEATER DATA SHEET\nCrude Charge Heater (H-101)\nHeat absorption, MMBtu/hr        45.20\n"
                  "Bridgewall temperature (deg F)   1650\nRadiant section area, ft2        4200")
        outputs = run_research(root, use_ocr=False, workers=1, log=lambda _: None, client_documents=True)
        assert outputs.pdf.parent == default_output_dir(root, client_documents=True)
        facts = {f.param_key: f for f in list_facts(outputs.db, include_low=True)}
        assert facts["heat_duty"].value_std == pytest.approx(45.2 * 0.29307107)
        assert facts["suhu_bridgewall"].value_std == pytest.approx((1650 - 32) * 5 / 9)
        assert facts["heat_duty"].confidence == "tinggi" and facts["heat_duty"].equipment.startswith("Fired Heater")


@pytest.mark.parametrize("text,key", [("CDU heater 11-F-101", "fired_heater"), ("ethylene cracking furnace", "cracking_furnace"),
                                      ("walking beam furnace di hot strip mill", "steel_furnace"),
                                      ("Hot blast stove BF-2", "steel_furnace")])
def test_refinery_and_steel_lexicon(text, key):
    assert find_equipment(text, load_lexicon())[0].key == key
