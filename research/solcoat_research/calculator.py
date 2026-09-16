"""Port Python dari src/utils/calc.js (Solcoat-Fuel-Energy-Saving-App, calculate.solcoat.com).

Rumus, urutan prioritas basis, konstanta, dan perilaku fallback sengaja dibuat identik dengan versi
JavaScript; kesetaraannya diuji terhadap keluaran calc.js di tests/fixtures/calc_js_parity.json.
Bila calc.js berubah, perbarui modul ini DAN buat ulang fixture (lihat tests/fixtures/make_calc_parity.mjs).
"""

import math
from dataclasses import dataclass, field

MMBTU_TO_GJ = 1.055056
GCAL_TO_GJ = 4.1868
KCAL_TO_GJ = 0.000004184
NO2_FACTOR = 0.0001            # ton / GJ
FEED_LIQUID_DENSITY = 0.85     # t/m³ [A]
DEFAULT_LHV = 0.046            # GJ/kg (LPG)
DEFAULT_EFFICIENCY = 85.0
EFFICIENCY_BOUNDS = (50.0, 99.0)
DEFAULT_MARKET_PRICE = 10.0    # USD/MMBtu — fallback aplikasi, BUKAN angka kanon
COVERAGE_FIBER = 2.5           # m²/galon
COVERAGE_CASTABLE = 3.5        # m²/galon

TO_GJ = {"Gcal/hr": GCAL_TO_GJ, "MMBtu/hr": MMBTU_TO_GJ, "GJ/hr": 1.0}
LHV_BY_FUEL = {"ng": 0.049, "fo": 0.041, "refinery": 0.045, "lpg": 0.046}
CO2_FACTORS = {"lpg": 0.0631, "ng": 0.0561, "fo": 0.0741, "refinery": 0.0600}
GAS_DENSITY = {"lpg": 2.0, "ng": 0.72, "refinery": 1.0, "mixed": 0.9}
DEFAULT_CO2 = 0.0600
DEFAULT_DENSITY = 0.9


@dataclass(frozen=True)
class FuelComponent:
    name: str
    percentage: float
    lhv: float
    price: float = 0.0


@dataclass(frozen=True)
class CalcInputs:
    fuel_type: str = "lpg"
    operation_hours: float = 8760
    direct_value: float = 0.0
    direct_unit: str = "Gcal/hr"
    fuel_rate: float = 0.0
    fuel_rate_unit: str = "kg/hr"
    feed_rate: float = 0.0
    feed_rate_unit: str = "ton/hr"
    design_duty: float = 0.0
    design_unit: str = "Gcal/hr"
    heater_efficiency: float = DEFAULT_EFFICIENCY
    actual_price: float = 0.0
    actual_price_currency: str = "USD"
    fuel_price_unit: str = "MMBtu"
    market_price: float = DEFAULT_MARKET_PRICE
    market_price_currency: str = "USD"
    coating_mode: str = "estimated"
    coating_cost: float = 0.0
    coating_cost_currency: str = "USD"
    coating_est_price: float = 0.0
    coating_est_currency: str = "USD"
    area_fiber: float = 0.0
    area_castable: float = 0.0
    include_tube_coating: bool = False
    tube_coating_gallons: float = 0.0
    scenarios: tuple[float, ...] = ()
    scenario_labels: tuple[str | None, ...] = ()
    exchange_rates: dict = field(default_factory=lambda: {"USD": 1.0})
    lhv_unit: str = "GJ/kg"
    custom_lhv: float = 0.0
    fuel_composition: tuple[FuelComponent, ...] = ()


@dataclass(frozen=True)
class ScenarioResult:
    percentage: float
    label: str | None
    energy_saving_gj: float
    energy_saving_mmbtu: float
    energy_saving_gcal: float
    financial_saving_usd: float
    financial_savings: dict
    co2_red: float
    no2_red: float
    roi_percent: float | None
    payback_months: float | None


@dataclass(frozen=True)
class Baseline:
    energy_gj: float
    energy_gcal: float
    cost_usd: float
    costs: dict
    energy_gj_hr: float
    energy_gcal_hr: float
    annual_energy_mmbtu: float
    annual_consumption_ton: float
    fuel_per_ton_product: float | None


@dataclass(frozen=True)
class CalcResult:
    calculation_basis: str
    baseline: Baseline
    scenarios: tuple[ScenarioResult, ...]
    assumptions: tuple[str, ...]
    is_cost_equivalent: bool
    co2_factor: float
    gallons_fiber: int
    gallons_castable: int
    gallons_total: float
    total_coating_cost_usd: float
    lhv: float


def _is_volumetric(inp: CalcInputs) -> bool:
    return inp.fuel_type == "mixed" and ("Nm3" in inp.lhv_unit or "Nm³" in inp.lhv_unit)


def _lhv_conversion(inp: CalcInputs) -> float:
    return KCAL_TO_GJ if inp.lhv_unit.startswith("kcal") else 1.0


def resolve_lhv(inp: CalcInputs) -> float:
    if inp.fuel_type != "mixed":
        return LHV_BY_FUEL.get(inp.fuel_type, DEFAULT_LHV)
    if inp.fuel_composition:
        conv = _lhv_conversion(inp)
        energy = sum((c.percentage or 0) / 100 * (c.lhv or 0) * conv for c in inp.fuel_composition)
        mass = sum((c.percentage or 0) / 100 for c in inp.fuel_composition)
        return energy if mass > 0 else DEFAULT_LHV
    return float(inp.custom_lhv) if inp.custom_lhv > 0 else DEFAULT_LHV


def _component_co2(name: str) -> float:
    lowered = (name or "").lower()
    if any(k in lowered for k in ("lpg", "propane", "butane")):
        return CO2_FACTORS["lpg"]
    if any(k in lowered for k in ("natural", "methane", "ng")):
        return CO2_FACTORS["ng"]
    if any(k in lowered for k in ("fuel oil", "hfo", "diesel")):
        return CO2_FACTORS["fo"]
    return DEFAULT_CO2


def resolve_co2_factor(inp: CalcInputs) -> float:
    if not (inp.fuel_type == "mixed" and inp.fuel_composition):
        return CO2_FACTORS.get(inp.fuel_type, DEFAULT_CO2)
    conv = _lhv_conversion(inp)
    weighted = total = 0.0
    for comp in inp.fuel_composition:
        energy = (comp.percentage or 0) / 100 * (comp.lhv or 0) * conv
        weighted += energy * _component_co2(comp.name)
        total += energy
    return weighted / total if total > 0 else DEFAULT_CO2


def _efficiency(inp: CalcInputs) -> float:
    low, high = EFFICIENCY_BOUNDS
    return min(max(float(inp.heater_efficiency or DEFAULT_EFFICIENCY), low), high)


def _js(value: float) -> str:
    """Format angka seperti template string JavaScript (25 bukan 25.0)."""
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def _baseline_energy(inp: CalcInputs, lhv: float) -> tuple[float, str]:
    if inp.direct_value > 0:
        return inp.direct_value * TO_GJ.get(inp.direct_unit, 1.0), "Direct fuel energy input"
    if inp.fuel_rate > 0:
        density = GAS_DENSITY.get(inp.fuel_type) or DEFAULT_DENSITY
        rate, unit = inp.fuel_rate, inp.fuel_rate_unit or "kg/hr"
        if _is_volumetric(inp):
            if unit == "Nm3/hr":
                gj = rate * lhv
                return gj, f"Direct fuel rate ({_js(rate)} Nm³/hr × {lhv:.6f} GJ/Nm³ = {gj:.2f} GJ/hr)"
            vol = rate / density
            gj = vol * lhv
            return gj, (f"Direct fuel rate ({_js(rate)} kg/hr ÷ {_js(density)} kg/Nm³ = {vol:.1f} Nm³/hr × "
                        f"{lhv:.6f} GJ/Nm³ = {gj:.2f} GJ/hr)")
        if unit == "Nm3/hr":
            kg = rate * density
            gj = kg * lhv
            return gj, (f"Direct fuel rate ({_js(rate)} Nm³/hr × {_js(density)} kg/Nm³ = {kg:.1f} kg/hr × "
                        f"{lhv:.6f} GJ/kg = {gj:.2f} GJ/hr)")
        gj = rate * lhv
        return gj, f"Direct fuel rate ({_js(rate)} kg/hr × {lhv:.6f} GJ/kg = {gj:.2f} GJ/hr)"
    if inp.design_duty > 0:
        duty = inp.design_duty * TO_GJ.get(inp.design_unit, 1.0)
        return duty / (_efficiency(inp) / 100), "Design heat duty"
    return 0.0, "Insufficient data"


def _to_usd(amount: float, currency: str, rates: dict) -> float:
    if not amount or math.isnan(amount):
        return 0.0
    if currency == "USD":
        return amount
    rate = rates.get(currency)
    return amount / rate if rate else amount


def _price_per_mmbtu_usd(price: float, currency: str, unit: str, lhv_gj_kg: float, rates: dict) -> float:
    usd = _to_usd(price or 0, currency, rates)
    if unit == "MT":
        energy_per_mt = lhv_gj_kg * 1000 / MMBTU_TO_GJ
        return usd / energy_per_mt if energy_per_mt > 0 else 0.0
    return usd


def _energy_price(inp: CalcInputs, lhv: float) -> tuple[float, bool]:
    rates, unit = inp.exchange_rates, inp.fuel_price_unit or "MMBtu"
    if inp.fuel_type == "refinery":
        price = _price_per_mmbtu_usd(inp.market_price or DEFAULT_MARKET_PRICE, inp.market_price_currency, unit, lhv, rates)
        return price / MMBTU_TO_GJ, True
    if inp.fuel_type == "mixed" and inp.fuel_composition:
        conv = KCAL_TO_GJ if inp.lhv_unit == "kcal/kg" else 1.0
        cost = mmbtu = 0.0
        for comp in inp.fuel_composition:
            lhv_gj = (comp.lhv or 0) * conv
            energy_mmbtu = (comp.percentage or 0) / 100 * lhv_gj / MMBTU_TO_GJ
            cost += energy_mmbtu * _price_per_mmbtu_usd(comp.price, inp.actual_price_currency, unit, lhv_gj, rates)
            mmbtu += energy_mmbtu
        price_gj = ((cost / mmbtu) if mmbtu > 0 else 0.0) / MMBTU_TO_GJ
    else:
        price_gj = _price_per_mmbtu_usd(inp.actual_price, inp.actual_price_currency, unit, lhv, rates) / MMBTU_TO_GJ
    if price_gj == 0:
        return _to_usd(inp.market_price or DEFAULT_MARKET_PRICE, inp.market_price_currency, rates) / MMBTU_TO_GJ, True
    return price_gj, False


def _annual_consumption_ton(inp: CalcInputs, basis: str, annual_gj: float, lhv: float) -> float:
    if inp.fuel_rate > 0 and basis.startswith("Direct fuel rate"):
        kg_hr = inp.fuel_rate
        if (inp.fuel_rate_unit or "kg/hr") == "Nm3/hr":
            kg_hr = inp.fuel_rate * (GAS_DENSITY.get(inp.fuel_type) or DEFAULT_DENSITY)
        return kg_hr * inp.operation_hours / 1000
    if lhv > 0:
        mass_lhv = lhv / (GAS_DENSITY.get(inp.fuel_type) or DEFAULT_DENSITY) if _is_volumetric(inp) else lhv
        return annual_gj / mass_lhv / 1000
    return 0.0


def coating_gallons(area_fiber: float, area_castable: float) -> tuple[int, int]:
    fiber = math.ceil(area_fiber / COVERAGE_FIBER) if area_fiber > 0 else 0
    castable = math.ceil(area_castable / COVERAGE_CASTABLE) if area_castable > 0 else 0
    return fiber, castable


def _assumptions(inp: CalcInputs, basis: str, lhv: float, co2: float, equivalent: bool) -> list[str]:
    notes: list[str] = []
    if basis.startswith("Direct fuel rate"):
        volumetric = _is_volumetric(inp)
        notes.append(f"LHV of {lhv:.6f} {'GJ/Nm³' if volumetric else 'GJ/kg'} ({inp.fuel_type}) used for energy conversion.")
        unit = inp.fuel_rate_unit or "kg/hr"
        if (unit == "Nm3/hr" and not volumetric) or (unit == "kg/hr" and volumetric):
            density = GAS_DENSITY.get(inp.fuel_type) or DEFAULT_DENSITY
            notes.append(f"Gas density assumed at {_js(density)} kg/Nm³ for {inp.fuel_type} unit cross-conversion.")
        if inp.feed_rate > 0:
            notes.append(f"Feed rate of {_js(inp.feed_rate)} {inp.feed_rate_unit or 'ton/hr'} used to calculate "
                         "specific fuel consumption (kg/ton).")
    elif basis == "Direct fuel energy input":
        notes.append(f"LHV of {lhv:.6f} GJ/kg ({inp.fuel_type}) used to estimate mass flow.")
    elif basis == "Design heat duty":
        notes.append(f"LHV of {lhv:.6f} GJ/kg ({inp.fuel_type}) used to estimate mass flow.")
        notes.append(f"Heater efficiency of {_js(_efficiency(inp))}% used to back-calculate fuel firing rate from design duty.")
    if equivalent:
        notes.append(f"Using equivalent market energy price ({_js(inp.market_price or DEFAULT_MARKET_PRICE)} "
                     f"{inp.market_price_currency}/MMBtu) for financial estimation.")
    notes.append(f"CO2 emission factor: {co2:.4f} ton CO2/GJ for {inp.fuel_type} (IPCC/IEA reference).")
    if inp.coating_mode == "estimated":
        details = [f"{_js(inp.area_fiber)} m² Fiber"] if inp.area_fiber > 0 else []
        details += [f"{_js(inp.area_castable)} m² Castable"] if inp.area_castable > 0 else []
        details += ["Tube Coating included"] if inp.include_tube_coating else []
        notes.append(f"Coating cost estimated from: {', '.join(details)}.")
    return notes


def validate_inputs(inp: CalcInputs) -> tuple[bool, str]:
    if inp.direct_value > 0 or inp.fuel_rate > 0 or inp.design_duty > 0:
        return True, ""
    return False, "Please enter at least one data source: Fuel Energy Input, Fuel Rate, or Design Heat Duty."


def _scenario(inp: CalcInputs, idx: int, pct: float, annual_gj: float, price_gj: float, co2: float,
              coating_usd: float) -> ScenarioResult:
    saving_gj = annual_gj * pct / 100
    saving_usd = saving_gj * price_gj
    roi = payback = None
    if coating_usd > 0 and saving_usd > 0:
        payback = coating_usd / (saving_usd / 12)
        roi = (saving_usd - coating_usd) / coating_usd * 100
    return ScenarioResult(
        percentage=pct, label=inp.scenario_labels[idx] if idx < len(inp.scenario_labels) else None,
        energy_saving_gj=saving_gj, energy_saving_mmbtu=saving_gj / MMBTU_TO_GJ,
        energy_saving_gcal=saving_gj / GCAL_TO_GJ, financial_saving_usd=saving_usd,
        financial_savings={c: saving_usd * r for c, r in inp.exchange_rates.items()},
        co2_red=saving_gj * co2, no2_red=saving_gj * NO2_FACTOR, roi_percent=roi, payback_months=payback,
    )


def calculate(inp: CalcInputs) -> CalcResult:
    lhv = resolve_lhv(inp)
    co2 = resolve_co2_factor(inp)
    energy_gj_hr, basis = _baseline_energy(inp, lhv)
    annual_gj = energy_gj_hr * inp.operation_hours
    price_gj, equivalent = _energy_price(inp, lhv)
    baseline_usd = annual_gj * price_gj

    fuel_per_ton = None
    annual_ton = _annual_consumption_ton(inp, basis, annual_gj, lhv)
    if inp.feed_rate > 0:
        feed_t_hr = inp.feed_rate * FEED_LIQUID_DENSITY if (inp.feed_rate_unit or "ton/hr") == "m3/hr" else inp.feed_rate
        annual_feed = feed_t_hr * inp.operation_hours
        fuel_per_ton = annual_ton * 1000 / annual_feed if annual_feed > 0 else None

    gal_fiber, gal_castable = coating_gallons(inp.area_fiber, inp.area_castable)
    gal_tube = inp.tube_coating_gallons if inp.include_tube_coating else 0
    if inp.coating_mode == "estimated":
        per_gal_usd = _to_usd(inp.coating_est_price, inp.coating_est_currency, inp.exchange_rates)
        coating_usd = (gal_fiber + gal_castable + gal_tube) * per_gal_usd
    else:
        coating_usd = _to_usd(inp.coating_cost, inp.coating_cost_currency, inp.exchange_rates)

    return CalcResult(
        calculation_basis=basis,
        baseline=Baseline(
            energy_gj=annual_gj, energy_gcal=annual_gj / GCAL_TO_GJ, cost_usd=baseline_usd,
            costs={c: baseline_usd * r for c, r in inp.exchange_rates.items()},
            energy_gj_hr=energy_gj_hr, energy_gcal_hr=energy_gj_hr / GCAL_TO_GJ,
            annual_energy_mmbtu=annual_gj / MMBTU_TO_GJ, annual_consumption_ton=annual_ton,
            fuel_per_ton_product=fuel_per_ton,
        ),
        scenarios=tuple(_scenario(inp, i, pct, annual_gj, price_gj, co2, coating_usd)
                        for i, pct in enumerate(inp.scenarios)),
        assumptions=tuple(_assumptions(inp, basis, lhv, co2, equivalent)),
        is_cost_equivalent=equivalent, co2_factor=co2, gallons_fiber=gal_fiber, gallons_castable=gal_castable,
        gallons_total=gal_fiber + gal_castable + gal_tube, total_coating_cost_usd=coating_usd, lhv=lhv,
    )
