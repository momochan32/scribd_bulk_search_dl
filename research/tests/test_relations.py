import pytest

from solcoat_research.entities import classify_source, find_equipment, generic_heading, normalize_plant
from solcoat_research.facts import Scope, extract_page_facts
from solcoat_research.lexicon import load_lexicon
from solcoat_research.normalize import normalize_text
from solcoat_research.quantities import find_quantities
from solcoat_research.validate import base_flags, conflict_flags

LEX = load_lexicon()


def _facts(text: str, **kwargs):
    return extract_page_facts(normalize_text(text), 1, "id", LEX, **kwargs).facts


def _by_param(facts, key):
    return [f for f in facts if f.param_key == key]


class TestQuantities:
    def test_range_and_negative_values(self):
        found = find_quantities(normalize_text("Temperatur : -33 oC (ke storage), 20-38 oC (ke urea)"))
        assert [(q.value, q.value_max) for q in found] == [(-33.0, None), (20.0, 38.0)]

    def test_dash_between_values_is_not_a_minus_sign(self):
        (q,) = find_quantities(normalize_text("Temperatur in/out : 400°C - 390°C"))
        assert (q.value, q.value_max) == (400.0, 390.0)

    def test_price_with_currency_prefix(self):
        (q,) = find_quantities("penurunan hampir USD0,82 per mmbtu")
        assert q.unit.key == "usd_mmbtu" and q.value == pytest.approx(0.82)

    def test_energy_total_in_million_mmbtu(self):
        (q,) = find_quantities("Total penghematan energi adalah 6,91 juta MMBTU.")
        assert q.value_std == pytest.approx(6.91 * 1.055056e6)

    def test_equipment_tag_is_not_a_quantity(self):
        assert find_quantities("Primary Reformer (1-H-101) dan 101-B") == []


class TestEntities:
    def test_tags_and_exclusions(self):
        mentions = find_equipment("sulphur furnace (B 1101) dan Boiler 1102. Air umpan boiler dipompa.", LEX)
        assert [(m.key, m.tag) for m in mentions] == [("sulfur_furnace", "B 1101"), ("boiler", "1102")]

    def test_tag_split_across_line_is_joined_in_flat_text(self):
        (mention,) = find_equipment("Waste Heat Recovery Primary Reformer (1-H- 101).", LEX)[1:]
        assert (mention.key, mention.tag) == ("primary_reformer", "1-H-101")

    def test_generic_heading(self):
        assert generic_heading("3. Desulfurizer (1-R-101 A/B)") == ("Desulfurizer", "1-R-101 A/B")
        assert generic_heading("Proses desulfurisasi berguna untuk menghilangkan sulfur") is None

    @pytest.mark.parametrize("raw,expected", [("PABRIK-1A", "Pabrik 1A"), ("kaltim-5", "Kaltim 5"),
                                              ("Unit ZA III", "Unit ZA III")])
    def test_normalize_plant(self, raw, expected):
        assert normalize_plant(raw) == expected

    def test_plant_company_mapping(self):
        assert LEX.company_for_plant("Kaltim 3") == "Pupuk Kalimantan Timur"
        assert LEX.company_for_plant("Pabrik 1A") == ""

    def test_classify_source(self):
        assert classify_source("Laporan-Kerja-Praktek-PT-X", "", LEX) == ("Laporan kerja praktik (mahasiswa)", "sekunder")
        assert classify_source("Kultur-Jaringan", "", LEX) == ("Lainnya", "belum diketahui")


class TestFacts:
    SPEC_PAGE = """unit ammonia Kaltim-3
2.
Primary Reformer (1-H-101)
Fungsi
: tempat reaksi reforming
Tipe
: side fired
Temperatur outlet
: 800 °C
Tekanan
: 38 kg/cm'G
Methanator Trim Heater
Fungsi
: memanaskan gas
Temperatur
: 300 °C
"""

    def test_spec_block_links_values_to_heading_with_high_confidence(self):
        facts = _facts(self.SPEC_PAGE)
        (outlet,) = _by_param(facts, "suhu_outlet")
        assert outlet.equipment.key == "primary_reformer" and outlet.equipment.tag == "1-H-101"
        assert outlet.confidence == "tinggi" and outlet.plant == "Kaltim 3"
        (pressure,) = _by_param(facts, "tekanan")
        assert pressure.value_std == pytest.approx(38 * 0.980665)

    def test_attributes_are_kept_for_target_equipment(self):
        attrs = {f.param_label: f.text_value for f in _facts(self.SPEC_PAGE)
                 if f.param_key == "atribut" and f.equipment.key == "primary_reformer"}
        assert attrs == {"Fungsi": "tempat reaksi reforming", "Tipe": "side fired"}

    def test_untagged_equipment_block_starts_new_scope(self):
        heater_temp = [f for f in _by_param(_facts(self.SPEC_PAGE), "suhu_operasi") if f.value == 300]
        assert heater_temp and heater_temp[0].equipment.label == "Methanator Trim Heater"

    def test_same_sentence_relation_and_part_attaches_to_parent(self):
        text = ("Gas masuk ke Primary Reformer untuk dipanaskan hingga mencapai temperatur 749 oC. "
                "Burner tersusun 4 sisi X 7 row X 25 burner = 700 burner.")
        facts = _facts(text)
        (temp,) = _by_param(facts, "suhu_operasi")
        assert temp.equipment.key == "primary_reformer" and temp.confidence == "sedang"
        burners = _by_param(facts, "jumlah_burner")
        assert {f.value for f in burners} == {25.0, 700.0}
        assert all(f.equipment.key == "primary_reformer" and f.equipment.component == "Burner" for f in burners)

    def test_generic_furnace_word_attaches_to_carried_reformer(self):
        carry = Scope("primary_reformer", "Primary Reformer", "A", "H-0201")
        (fact,) = _by_param(_facts("Tekanan dalam furnace dijaga pada 1 atm.", carry=carry), "tekanan")
        assert fact.equipment.key == "primary_reformer"

    def test_percent_without_keyword_is_dropped(self):
        assert _facts("Primary Reformer beroperasi 100% sepanjang tahun") == ()

    def test_emissivity_is_extracted(self):
        (fact,) = _by_param(_facts("Refraktori castable memiliki emisivitas sekitar 0,55 pada 900 oC."), "emisivitas")
        assert fact.value == pytest.approx(0.55)

    def test_strategic_sentences(self):
        result = extract_page_facts("Perusahaan menjalankan program efisiensi energi di pabrik amoniak.", 1, "id", LEX)
        assert result.strategic and result.strategic[0][0] == "efisiensi energi"


class TestValidate:
    def test_out_of_range_and_ocr_flags(self):
        (fact,) = _by_param(_facts("Primary Reformer beroperasi pada temperatur 5000 oC."), "suhu_operasi")
        flags = base_flags(fact, "ocr", LEX).flags
        assert any("di luar rentang" in f for f in flags)
        assert any(f.startswith("angka hasil OCR") for f in flags)

    def test_conflicting_values_across_documents(self):
        (a,) = _by_param(_facts("Primary Reformer (1-H-101) temperatur 800 oC."), "suhu_operasi")
        (b,) = _by_param(_facts("Primary Reformer (1-H-101) temperatur 1000 oC."), "suhu_operasi")
        flagged = conflict_flags([(1, "X|-|primary_reformer|1-H-101", "doc1.pdf", a),
                                  (2, "X|-|primary_reformer|1-H-101", "doc2.pdf", b)])
        assert set(flagged) == {1, 2} and "berbeda antar sumber" in flagged[1]

    def test_same_value_in_two_documents_is_not_a_conflict(self):
        (a,) = _by_param(_facts("Primary Reformer (1-H-101) temperatur 800 oC."), "suhu_operasi")
        assert conflict_flags([(1, "X|eq", "doc1.pdf", a), (2, "X|eq", "doc2.pdf", a)]) == {}
