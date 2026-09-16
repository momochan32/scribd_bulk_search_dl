"""Kesetaraan angka calculator.py dengan calc.js asli (calculate.solcoat.com)."""

import json
from pathlib import Path

import pytest

from solcoat_research.calculator import CalcInputs, FuelComponent, calculate, coating_gallons, validate_inputs

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "calc_js_parity.json").read_text())
REL = 1e-9


def _from_js(js: dict) -> CalcInputs:
    basis, costs = js.get("basisData", {}), js.get("costs", {})
    return CalcInputs(
        fuel_type=js["fuelType"], operation_hours=js.get("operationHours", 8760),
        direct_value=basis.get("directValue", 0), direct_unit=basis.get("directUnit", "Gcal/hr"),
        fuel_rate=basis.get("fuelRate", 0), fuel_rate_unit=basis.get("fuelRateUnit", "kg/hr"),
        feed_rate=basis.get("feedRate", 0), feed_rate_unit=basis.get("feedRateUnit", "ton/hr"),
        design_duty=basis.get("designDuty", 0), design_unit=basis.get("designUnit", "Gcal/hr"),
        heater_efficiency=js.get("heaterEfficiency", 85),
        actual_price=costs.get("actualPrice", 0), actual_price_currency=costs.get("actualPriceCurrency", "USD"),
        fuel_price_unit=costs.get("fuelPriceUnit", "MMBtu"),
        market_price=costs.get("marketPrice", 10), market_price_currency=costs.get("marketPriceCurrency", "USD"),
        coating_mode=costs.get("coatingMode", "fixed"), coating_cost=costs.get("coatingCost", 0),
        coating_cost_currency=costs.get("coatingCostCurrency", "USD"),
        coating_est_price=costs.get("coatingEstPrice", 0), coating_est_currency=costs.get("coatingEstCurrency", "USD"),
        area_fiber=costs.get("coatingAreaFiber", 0), area_castable=costs.get("coatingAreaCastable", 0),
        include_tube_coating=costs.get("includeTubeCoating", False),
        tube_coating_gallons=costs.get("tubeCoatingGallons", 0),
        scenarios=tuple(js.get("scenarios", ())), scenario_labels=tuple(js.get("scenarioLabels", ())),
        exchange_rates=js["exchangeRates"], lhv_unit=js.get("lhvUnit", "GJ/kg"), custom_lhv=js.get("customLHV", 0),
        fuel_composition=tuple(FuelComponent(c["name"], c["percentage"], c["lhv"], c.get("price", 0))
                               for c in js.get("fuelComposition", ())),
    )


def _approx(expected):
    return None if expected is None else pytest.approx(expected, rel=REL, abs=1e-9)


@pytest.mark.parametrize("case", sorted(FIXTURE))
def test_matches_calc_js(case):
    js_inputs, expected = FIXTURE[case]["inputs"], FIXTURE[case]["result"]
    result = calculate(_from_js(js_inputs))

    assert result.calculation_basis == expected["calculationBasis"]
    assert list(result.assumptions) == expected["assumptions"]
    assert result.is_cost_equivalent == expected["isCostEquivalent"]
    assert result.co2_factor == _approx(expected["co2Factor"])

    b, eb = result.baseline, expected["baseline"]
    for py_name, js_name in (("energy_gj", "energyGJ"), ("energy_gcal", "energyGcal"), ("cost_usd", "costUSD"),
                             ("energy_gj_hr", "energyGJHr"), ("energy_gcal_hr", "energyGcalHr"),
                             ("annual_energy_mmbtu", "annualEnergyMMBtu"),
                             ("annual_consumption_ton", "annualConsumptionTon"),
                             ("fuel_per_ton_product", "fuelPerTonProduct")):
        assert getattr(b, py_name) == _approx(eb[js_name]), py_name
    assert b.costs == {k: _approx(v) for k, v in eb["costs"].items()}

    assert len(result.scenarios) == len(expected["scenarios"])
    for sc, es in zip(result.scenarios, expected["scenarios"]):
        assert (sc.percentage, sc.label) == (es["percentage"], es["label"])
        for py_name, js_name in (("energy_saving_gj", "energySavingGJ"), ("energy_saving_mmbtu", "energySavingMMBtu"),
                                 ("financial_saving_usd", "financialSavingUSD"), ("co2_red", "co2Red"),
                                 ("no2_red", "no2Red"), ("roi_percent", "roiPercent"),
                                 ("payback_months", "paybackMonths")):
            assert getattr(sc, py_name) == _approx(es[js_name]), f"{case} {py_name}"
        assert sc.financial_savings == {k: _approx(v) for k, v in es["financialSavings"].items()}
        assert result.total_coating_cost_usd == _approx(es["totalCoatingCostUSD"])


def test_gallons_round_up_per_substrate():
    assert coating_gallons(800, 0) == (320, 0)
    assert coating_gallons(121, 463) == (49, 133)
    assert coating_gallons(0, 0) == (0, 0)


def test_validation_requires_one_energy_source():
    ok, message = validate_inputs(CalcInputs(fuel_type="ng"))
    assert not ok and "at least one data source" in message
    assert validate_inputs(CalcInputs(fuel_type="ng", design_duty=10))[0]
