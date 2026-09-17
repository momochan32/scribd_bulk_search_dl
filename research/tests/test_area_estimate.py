"""Estimasi luas hot face dari dimensi [A]."""

import math

import pytest

from solcoat_research.area_estimate import DimensionFact, box, classify, cylinder, estimate_from_dimensions


def _dim(value, raw, snippet, page=50, order=1, qualifier=""):
    return DimensionFact(value, raw, qualifier, snippet, page, order, f"Laporan h.{page}")


def test_cylinder_with_and_without_ends():
    with_ends = cylinder(4340, 19860)
    assert with_ends.area_m2 == pytest.approx(math.pi * 4.34 * 19.86 + 2 * math.pi * 4.34 ** 2 / 4)
    assert with_ends.formula.endswith("= 300,4 m²")
    assert cylinder(4340, 19860, include_ends=False).area_m2 == pytest.approx(math.pi * 4.34 * 19.86)


def test_box_walls_roof_and_floor():
    assert box(12000, 6000, 15000).area_m2 == pytest.approx(2 * 18 * 15 + 72)
    assert box(12000, 6000, 15000, include_roof=False).area_m2 == pytest.approx(540)
    assert box(12000, 6000, 15000, include_floor=True).area_m2 == pytest.approx(540 + 144)


@pytest.mark.parametrize("bad", [(0, 100), (100, -1)])
def test_cylinder_rejects_non_positive(bad):
    with pytest.raises(ValueError):
        cylinder(*bad)


@pytest.mark.parametrize("snippet,raw,expected", [
    ("Bentuk Silinder Kapasitas 600 ton/hari Diameter Dalam 4340 mm Tinggi", "4340 mm", ("diameter", "dalam")),
    ("Diameter Dalam 4340 mm Tinggi 19860 mm T desain", "19860 mm", ("tinggi", None)),
    ("Dimensi Panjang : 12200 mm Diameter luar : 2438 mm", "2438 mm", ("diameter", "luar")),
    ("Panjang shell : 880 mm Diamater shell : 625 mm Diameter tube : 20 mm", "20 mm", None),
    ("radiant box lebar : 6000 mm", "6000 mm", ("lebar", None)),
    ("Kapasitas 600 ton/hari 4340 mm", "4340 mm", None),
])
def test_classify_from_text_before_value(snippet, raw, expected):
    assert classify(_dim(1, raw, snippet)) == expected


def test_estimate_prefers_inner_diameter_and_real_sulfur_furnace_text():
    snippet = "Bentuk Silinder Kapasitas 600 ton/hari Diameter Luar 4500 mm Diameter Dalam 4340 mm Tinggi 19860 mm"
    facts = [_dim(4500, "4500 mm", snippet, order=1), _dim(4340, "4340 mm", snippet, order=2),
             _dim(19860, "19860 mm", snippet, order=3)]
    estimate = estimate_from_dimensions(facts)
    assert estimate.shape == "silinder" and estimate.dimensions_mm == (("diameter", 4340), ("tinggi", 19860))
    assert estimate.sources == ("Laporan h.50",)


def test_estimate_from_id_x_tl_sequence():
    facts = [_dim(1900, "1900 mm", "", order=1, qualifier="ID x TL-TL"),
             _dim(4600, "4600 mm", "", order=2, qualifier="ID x TL-TL")]
    assert estimate_from_dimensions(facts).dimensions_mm == (("diameter", 1900), ("tinggi", 4600))


def test_estimate_box_when_no_diameter():
    snippet = "Radiant box panjang : 12000 mm lebar : 6000 mm tinggi : 15000 mm"
    facts = [_dim(12000, "12000 mm", snippet, order=1), _dim(6000, "6000 mm", snippet, order=2),
             _dim(15000, "15000 mm", snippet, order=3)]
    estimate = estimate_from_dimensions(facts)
    assert estimate.shape == "kotak" and estimate.dimensions_mm == (("panjang", 15000), ("lebar", 6000), ("tinggi", 12000))


def test_no_estimate_without_complete_dimensions():
    assert estimate_from_dimensions([_dim(4340, "4340 mm", "Diameter Dalam 4340 mm")]) is None
    assert estimate_from_dimensions([]) is None
