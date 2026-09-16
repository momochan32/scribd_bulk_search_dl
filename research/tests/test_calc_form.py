"""Form 'Hitung dengan Asumsi': aturan overwrite, prefill dari riset, kurs, dan PDF kalkulasi."""

import io
import json
from pathlib import Path

import pymupdf
import pytest

from solcoat_research.calc_form import (AUTO_CONFIDENCE, FIELDS, FieldInput, FormError, build_inputs, is_locked,
                                        parse_number, result_warnings)
from solcoat_research.calc_prefill import EquipmentCandidate, KnownValue, load_candidates
from solcoat_research.calc_report import build_calc_pdf, default_filename
from solcoat_research.calculator import calculate
from solcoat_research.extract import OcrSettings
from solcoat_research.fx import fetch_usd_idr
from solcoat_research.pipeline import ScanConfig, run_scan
from test_pipeline_e2e import _text_pdf

RESEARCH_AREA = KnownValue(463.0, "m2", "Laporan KP h.12", "tinggi", "463 m2")
FX = KnownValue(17697.0, "IDR", "frankfurter.dev", AUTO_CONFIDENCE, "17697")


def _base(**overrides) -> dict[str, FieldInput]:
    texts = {"tag": "H-0201", "description": "Primary Reformer PKT", "fuel_type": "ng", "design_duty": "150",
             "actual_price": "6,33", "area_total": "", "fx_date": "2026-09-15"}
    fields = {spec.key: FieldInput(spec.key, texts.get(spec.key, "")) for spec in FIELDS}
    fields["area_total"] = FieldInput("area_total", "", known=RESEARCH_AREA)
    fields["usd_idr"] = FieldInput("usd_idr", "", known=FX)
    fields.update(overrides)
    return fields


class TestOverwriteRule:
    def test_known_value_is_used_and_locked_without_overwrite(self):
        form = build_inputs(_base(area_total=FieldInput("area_total", "9999", known=RESEARCH_AREA)))
        assert form.inputs.area_castable == 463.0
        assert form.value("area_total").origin == "riset: Laporan KP h.12"
        assert is_locked(FieldInput("area_total", "", known=RESEARCH_AREA))

    def test_overwrite_checkbox_unlocks_new_value(self):
        form = build_inputs(_base(area_total=FieldInput("area_total", "1.200", known=RESEARCH_AREA, overwrite=True)))
        assert form.inputs.area_castable == 1200.0
        assert form.value("area_total").origin == "overwrite pengguna"

    def test_overwrite_checked_but_empty_is_rejected(self):
        with pytest.raises(FormError, match="Overwrite dicentang"):
            build_inputs(_base(area_total=FieldInput("area_total", " ", known=RESEARCH_AREA, overwrite=True)))

    def test_overwrite_with_invalid_number_is_rejected(self):
        with pytest.raises(FormError, match="bukan angka"):
            build_inputs(_base(usd_idr=FieldInput("usd_idr", "tujuh belas ribu", known=FX, overwrite=True)))

    def test_unknown_field_needs_no_checkbox(self):
        form = build_inputs(_base(price_per_gallon=FieldInput("price_per_gallon", "70.000.000")))
        assert form.price_per_gallon_idr == 70_000_000
        assert "Harga override Rp 70.000.000/galon, default Rp 85 jt." in form.warnings

    def test_kurs_origin_is_automatic(self):
        assert build_inputs(_base()).value("usd_idr").origin == "kurs otomatis"


class TestValidation:
    def test_requires_energy_basis(self):
        with pytest.raises(FormError, match="basis energi"):
            build_inputs(_base(design_duty=FieldInput("design_duty", "")))

    def test_required_area_when_not_known(self):
        with pytest.raises(FormError, match="Total luas area coating wajib"):
            build_inputs(_base(area_total=FieldInput("area_total", "")))

    def test_range_limits(self):
        with pytest.raises(FormError, match="maksimal 100"):
            build_inputs(_base(fiber_share=FieldInput("fiber_share", "150")))

    @pytest.mark.parametrize("text,expected", [("85.000.000", 85e6), ("85,000,000", 85e6), ("1.234,5", 1234.5),
                                               ("6,33", 6.33), ("1234.5", 1234.5), ("1.200", 1200.0), ("0,125", 0.125), ("12.5", 12.5)])
    def test_parse_number_formats(self, text, expected):
        assert parse_number(text) == pytest.approx(expected)


class TestCalculationFlow:
    def test_defaults_follow_solcoat_rules(self):
        form = build_inputs(_base())
        inp = form.inputs
        assert (inp.operation_hours, inp.coating_est_price, inp.scenarios) == (8760, 85_000_000, (2.5, 5.0, 7.0))
        result = calculate(inp)
        assert result.gallons_castable == 133  # ceil(463 / 3,5)
        assert result.total_coating_cost_usd * 17697 == pytest.approx(133 * 85_000_000)

    def test_fiber_share_splits_area_and_warns(self):
        form = build_inputs(_base(fiber_share=FieldInput("fiber_share", "25")))
        assert (form.inputs.area_fiber, form.inputs.area_castable) == (pytest.approx(115.75), pytest.approx(347.25))
        assert any("ceramic fiber" in w for w in form.warnings)

    def test_coal_boiler_warning(self):
        coal = EquipmentCandidate("id", "Pusri", "Pusri 2B", "coal_boiler", "Boiler Batubara", "", "A")
        assert any("TIDAK berlaku" in w for w in build_inputs(_base(), candidate=coal).warnings)

    def test_payback_too_fast_is_reported_once(self):
        result = calculate(build_inputs(_base(design_duty=FieldInput("design_duty", "5000"))).inputs)
        assert any("< 6 bulan" in w for w in result_warnings(result))

    def test_pdf_contains_sections_without_guarantee(self, tmp_path: Path):
        form = build_inputs(_base())
        path = build_calc_pdf(form, calculate(form.inputs), tmp_path / default_filename(form))
        text = "".join(page.get_text() for page in pymupdf.open(path))
        for expected in ("Identifikasi Furnace", "Data Baseline", "Hasil Estimasi", "bukan komitmen",
                         "riset: Laporan KP h.12", "kurs otomatis", "2026-09-15", "material"):
            assert expected in text
        assert "Garansi" not in text and "370" not in text and "85.000.000" not in text

    def test_pdf_can_show_price_per_gallon(self, tmp_path: Path):
        form = build_inputs(_base())
        path = build_calc_pdf(form, calculate(form.inputs), tmp_path / "a.pdf", show_price_per_gallon=True)
        assert "85.000.000" in "".join(page.get_text() for page in pymupdf.open(path))


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestFxAndPrefill:
    def test_fx_parses_rate_and_date(self):
        payload = json.dumps({"date": "2026-09-15", "rates": {"IDR": 17697}}).encode()
        rate = fetch_usd_idr(opener=lambda req, timeout, context: _Resp(payload))
        assert (rate.usd_idr, rate.date) == (17697.0, "2026-09-15")

    def test_fx_failure_returns_none_instead_of_inventing(self):
        def offline(*args, **kwargs):
            raise OSError("offline")

        assert fetch_usd_idr(opener=offline) is None

    def test_prefill_reads_research_database(self, tmp_path: Path):
        root = tmp_path / "Pupuk_Kaltim"
        (root / "Pupuk_Kaltim").mkdir(parents=True)
        _text_pdf(root / "Pupuk_Kaltim" / "KP-PKT_1.pdf",
                  "Primary Reformer (1-H-101)\nTipe : side fired, bahan bakar gas alam\nHeat duty : 40 MMBtu/hr\n"
                  "Surface area : 463 m2\nHarga gas rata-rata mencapai USD6,33 per mmbtu.")
        result = run_scan(ScanConfig(root, tmp_path / "out", workers=1, ocr=OcrSettings(enabled=False)),
                          log=lambda _: None)
        (candidate,) = [c for c in load_candidates(result.db_path) if c.key == "primary_reformer"]
        assert candidate.known["design_duty"].value == pytest.approx(40 * 0.29307107 * 3.6)
        assert candidate.known["area_total"].value == 463.0
        assert candidate.known["fuel_type"].value == "ng"
        assert candidate.display_name.startswith("Primary Reformer 1-H-101")

    def test_prefill_missing_database(self, tmp_path: Path):
        assert load_candidates(tmp_path / "tidak-ada.db") == []
