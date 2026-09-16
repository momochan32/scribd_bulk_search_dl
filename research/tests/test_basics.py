import pytest

from solcoat_research.normalize import flatten, logical_lines, normalize_text, repair_ligatures
from solcoat_research.numparse import detect_language, parse_number
from solcoat_research.text_quality import assess
from solcoat_research.units import match_unit


class TestParseNumber:
    @pytest.mark.parametrize("raw,lang,expected", [
        ("24.888", "id", 24888.0),
        ("39,2", "id", 39.2),
        ("0,207", "id", 0.207),
        ("1.234,5", "id", 1234.5),
        ("1,234.5", "en", 1234.5),
        ("61,800", "en", 61800.0),
        ("3.100.000", "id", 3100000.0),
        ("-33", "id", -33.0),
        ("800", "id", 800.0),
    ])
    def test_parses_locale_formats(self, raw, lang, expected):
        assert parse_number(raw, lang).value == pytest.approx(expected)

    def test_flags_comma_with_three_digits_on_indonesian_page(self):
        result = parse_number("24,888", "id")
        assert result.value == pytest.approx(24.888)
        assert result.is_ambiguous

    def test_rejects_non_numbers(self):
        assert parse_number("abc") is None
        assert parse_number("12.") is None


def test_detect_language():
    assert detect_language("Gas alam yang masuk ke dalam reformer dan dipanaskan untuk proses") == "id"
    assert detect_language("The gas is heated in the reformer and sent to the converter for the process") == "en"


class TestNormalize:
    def test_repairs_dropped_ligatures(self):
        assert repair_ligatures("Esiensi penggunaan energi") == "Efisiensi penggunaan energi"
        assert repair_ligatures("Co-fring ammonia") == "Co-firing ammonia"
        assert repair_ligatures("menangkap CO2 dari ue gas") == "menangkap CO2 dari flue gas"
        assert repair_ligatures("melakukan esiensi energi") == "melakukan efisiensi energi"

    def test_does_not_touch_valid_words(self):
        assert repair_ligatures("proses final dan fisik") == "proses final dan fisik"

    @pytest.mark.parametrize("raw,expected", [
        ("temperature ± 30oC dengan", "temperature ± 30 °C dengan"),
        ("T = 800ᵒC,P = 38 kg/cm2", "T = 800 °C,P = 38 kg/cm2"),
        ("Tekanan : 39,2 kg/cm'G", "Tekanan : 39,2 kg/cm2g"),
        ("45 kg/cnrG, 30 °C", "45 kg/cm2g, 30 °C"),
        ("24.888 Nm'/jam", "24.888 Nm3/jam"),
        ("Surface area : 1514 m?", "Surface area : 1514 m2"),
        ("luas 450 m²", "luas 450 m2"),
    ])
    def test_normalizes_ocr_units(self, raw, expected):
        assert normalize_text(raw) == expected

    def test_logical_lines_joins_split_key_values(self):
        text = "Natural gas KO drum (1-S-101)\nFungsi\n: memisahkan\nTipe\n: vertical\n1.\nDesulfurizer"
        assert logical_lines(text) == [
            "Natural gas KO drum (1-S-101)", "Fungsi : memisahkan", "Tipe : vertical", "1. Desulfurizer",
        ]

    def test_flatten(self):
        assert flatten("a\n  b\tc") == "a b c"


class TestTextQuality:
    def test_empty_page(self):
        assert assess("  12 ").status == "empty"

    def test_clean_indonesian_text_is_ok(self):
        text = ("Primary reformer bertujuan untuk membentuk syngas dengan mereaksikan gas alam dengan steam. "
                "Pada steam reforming digunakan katalis nikel-alumina yang ada dalam tube-tube untuk "
                "mempercepat reaksi gas alam dan steam.")
        assert assess(text).status == "ok"

    def test_corrupted_font_encoding_is_garbled(self):
        text = ('dibahas disini adalah menghitung koe8isien perpindahan panas konveksi 4h5 dan distribusi '
                'suhu urea &rilling dan udara pendingin sepanjang &rilling tower dengan dasar perhitungan '
                'nera6a panas pada &rilling tower @ambar ;"1 @ra8ik 9ubungan Suhu """""""""""')
        assert assess(text).status == "garbled"


class TestUnits:
    @pytest.mark.parametrize("text,key,std", [
        ("°C, tekanan", "degC", 800.0),
        ("kg/cm2g", "kgcm2", 784.532),
        ("MMBtu/hr", "mmbtu_h", 234.456856),
        ("Nm3/jam", "nm3_h", 800.0),
        ("m2 luas", "m2", 800.0),
        ("mm x", "mm", 800.0),
        ("m tinggi", "m", 800000.0),
        ("ton/hari", "ton_d", 800.0),
        ("MW listrik", "mw", 800.0),
    ])
    def test_matches_and_converts(self, text, key, std):
        unit, _ = match_unit(text)
        assert unit.key == key
        assert unit.to_std(800) == pytest.approx(std)

    def test_fahrenheit_to_celsius(self):
        unit, _ = match_unit("°F")
        assert unit.to_std(1650) == pytest.approx(898.89, abs=0.01)

    def test_case_sensitive_units(self):
        assert match_unit("mw") is None
        assert match_unit("Meter") is None
        assert match_unit("unit") is None
