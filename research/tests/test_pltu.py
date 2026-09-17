"""Mode PLTU: form → dict UNIT → PDF 9 bagian (engine baku), checklist §5, dan segregasi data antar klien."""

from dataclasses import replace
from datetime import date
from pathlib import Path

import pymupdf
import pytest

from solcoat_research.pltu import engine
from solcoat_research.pltu.pln_data import UNITS
from solcoat_research.pltu.unit_builder import (DEFAULT_STREAMS_TEXT, Performance, PltuFormError, PltuInputs, Zone,
                                                build_unit, checklist, generate_pdf, lining_stream, output_filename,
                                                parse_streams, parse_zones, scale_intervals, summary)


def _perf(up="UP Paiton", **over):
    u = UNITS[up]
    return replace(Performance(u.eaf, u.sof, u.efor, u.nphr, u.production_gwh, u.dtp_mw), **over)


def _inputs(**over) -> PltuInputs:
    base = PltuInputs(
        tag="PAITON-9", rev="Rev 12", client="PT PLN (Persero)", asset_name="PLTU 2 Jawa Timur - Unit Paiton 9",
        location="Probolinggo", up="UP Paiton", capacity_mw=660, boiler_class="PC", oem="Harbin Boiler Group",
        cod="12 Mei 2012", performance=_perf(),
        castable_zones=(Zone("Ash hopper slope dan knuckle", 180), Zone("Furnace arch atau nose", 70)),
        fiber_zones=(Zone("Penthouse roof dan floor seal", 38),),
        streams=(lining_stream(413, 0.050, 2),) + parse_streams(
            "Jam kerja pembersihan | 480 jam-orang x Rp 250.000 | 120.000.000 | tidak\n"
            "Coal Nozzle | Rp 1.200.000.000 per set - interval 3 tahun - faktor 0,30 | 120000000\n"
            "Tiny Oil Burner | interval 4 tahun - faktor 0,30 | 90000000\n"
            "Retubing | interval 5 tahun - faktor 0,20 | 200000000"),
        interval_label="Lining 2 tahun, coal nozzle 3 tahun, tiny oil burner 4 tahun, retubing 5 tahun",
        component_price_source="Company Profile PLN Pusharlis 2022", unit_spec_source="Katalog PLN",
        price_per_gallon=95_000_000, gallon_override=150, show_price_per_gallon=True)
    return replace(base, **over)


def test_lining_helper_matches_paiton_template():
    stream = lining_stream(413, 0.050, 2)
    assert stream.annual_value == pytest.approx(1_239_000_000)
    assert "49,56 ton" in stream.basis and stream.scales_with_interval


def test_summary_matches_engine_formulas():
    stats = summary(_inputs())
    assert stats["investment"] == 150 * 95_000_000
    assert stats["maintenance"] == pytest.approx(1_769_000_000)
    lost = 660 * 8760 * (1 - 0.9229)
    assert stats["production_low"] == pytest.approx(lost * 0.025 * 289_000)
    expected = 14_250_000_000 / ((1_769_000_000 + lost * 0.025 * 289_000) * 0.30) * 12
    assert stats["payback_30_months"] == pytest.approx(expected)


def test_gallons_round_up_to_tens_without_override():
    stats = summary(_inputs(gallon_override=None))
    assert stats["gallons"] == 80 + 20  # ceil(250/3,5/10)*10 + ceil(38/2,5/10)*10


@pytest.mark.parametrize("text,message", [("Arch 70", "format"), ("Arch ; -5", "harus > 0"), ("Arch ; abc", "bukan angka")])
def test_parse_zones_errors(text, message):
    with pytest.raises(PltuFormError, match=message):
        parse_zones(text, "castable")


def test_parse_zones_and_streams():
    assert parse_zones("Arch ; 70\n\nThroat ; 1.200,5", "castable") == (Zone("Arch", 70), Zone("Throat", 1200.5))
    streams = parse_streams(DEFAULT_STREAMS_TEXT)
    assert len(streams) == 2 and streams[0].scales_with_interval is False and streams[1].annual_value == 120_000_000
    with pytest.raises(PltuFormError, match="format"):
        parse_streams("hanya nama | 10")


def test_scale_intervals():
    assert scale_intervals("Lining 2 tahun, retubing 5 tahun", 4) == "Lining 8 tahun, retubing 20 tahun"


def test_checklist_blocks_missing_items_and_warns_rule_cases():
    errors, _ = checklist(_inputs(tag="", streams=(), castable_zones=(), fiber_zones=()))
    assert {"Tag unit wajib diisi", "Minimal satu aliran biaya perawatan yang dihindari",
            "Minimal satu zona hot face (castable atau ceramic fiber)"} <= set(errors)
    _, warnings = checklist(_inputs(castable_zones=(Zone("Waterwall?", 3000),), performance=_perf(eaf=85.0, overwritten=True)))
    text = " ".join(warnings)
    for fragment in ("waterwall ikut terhitung", "EAF 85%", "di-overwrite", "Harga override", "gabungan unit", "Boiler PC"):
        assert fragment in text


def test_filename_contains_tag_and_revision():
    assert output_filename(_inputs(tag="nagan raya 1", rev="Rev 0")) == "Solcoat_Calculation_NAGAN_RAYA_1_KLIEN_Rev_0.pdf"


def test_unit_dict_uses_pln_table_and_ten_sources(tmp_path: Path):
    unit = build_unit(_inputs(), tmp_path, today=date(2026, 9, 17))
    assert (unit["eaf"], unit["eaf_s"], unit["sof"], unit["nphr"], unit["dtp"]) == (92.29, "92,29", "7,35", "2.888,97", "1.460")
    assert len(unit["sumber"]) == 10 and unit["tanggal"] == "17/09/2026"
    assert unit["zona_luar"][0][0].startswith("Membrane waterwall")
    assert unit["interval_4x"].startswith("Lining 8 tahun")
    with pytest.raises(PltuFormError):
        build_unit(_inputs(rev=""), tmp_path)


def test_generated_pdf_has_nine_sections_and_no_other_client_text(tmp_path: Path):
    nagan = _inputs(tag="NAGAN-RAYA-1", rev="Rev 0", asset_name="PLTU Nagan Raya Unit 1", up="UP Nagan Raya",
                    capacity_mw=110, boiler_class="CFB", oem="", location="Aceh", performance=_perf("UP Nagan Raya"),
                    price_per_gallon=85_000_000, gallon_override=None, show_price_per_gallon=False)
    path = generate_pdf(nagan, tmp_path)
    assert path.name == "Solcoat_Calculation_NAGAN-RAYA-1_KLIEN_Rev_0.pdf" and path.exists()
    text = "".join(page.get_text() for page in pymupdf.open(path))
    for heading in ("1 - Identifikasi Unit", "2 - Lingkup Pekerjaan", "5 - Biaya Perawatan yang Dihindari",
                    "7 - Payback dan ROI", "8 - Sensitivitas", "9 - Sumber Data", "80,93%", "18,16%", "Konservatif"):
        assert heading in text
    assert "Paiton" not in text
    assert "Harga per galon" not in text


def test_engine_is_verbatim_copy_constants():
    assert (engine.NILAI_BAWAH, engine.NILAI_ATAS, engine.SHARE_DEPOSIT, engine.JAM) == (289_000, 621_000, 0.025, 8760)
    assert [r for _, r in engine.SKENARIO] == [0.15, 0.30, 0.50]
