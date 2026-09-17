"""NPV dengan degradasi emisivitas coating — aturan Solcoat: ε ~0,98 turun ke 0,75–0,85 dalam 6–8 tahun.

Manfaat tahun ke-t sebanding dengan selisih emisivitas terhadap substrat telanjang:
    faktor_t = (ε_t − ε_substrat) / (ε_awal − ε_substrat)
ε_t turun linear dari ε_awal ke ε_akhir selama `degradation_years`, lalu tetap. Nilai tengah tahun dipakai.
⚠️ Bertentangan dengan klaim company profile "stabil >0,96 sepanjang lifecycle" — konflik ini disebutkan di laporan.
"""

from dataclasses import dataclass

SUBSTRATE_EMISSIVITY = {"castable": 0.55, "ceramic fiber": 0.76}
IRR_BOUNDS = (-0.99, 10.0)
IRR_ITERATIONS = 200


@dataclass(frozen=True)
class NpvInputs:
    investment: float
    base_annual_saving: float          # manfaat tahunan pada ε baru (mis. dari kalkulator)
    discount_rate_pct: float = 10.0
    years: int = 10
    eps_initial: float = 0.98
    eps_end: float = 0.80
    degradation_years: float = 7.0
    eps_substrate: float = SUBSTRATE_EMISSIVITY["castable"]


@dataclass(frozen=True)
class YearRow:
    year: int
    emissivity: float
    factor: float
    saving: float
    discounted: float
    cumulative_discounted: float


@dataclass(frozen=True)
class NpvResult:
    rows: tuple[YearRow, ...]
    npv: float
    npv_without_degradation: float
    irr: float | None
    discounted_payback_years: float | None


def validate(inp: NpvInputs) -> None:
    if inp.investment <= 0 or inp.base_annual_saving <= 0:
        raise ValueError("Investasi dan manfaat tahunan harus > 0")
    if not 1 <= inp.years <= 40:
        raise ValueError("Horizon harus 1–40 tahun")
    if not 0 < inp.eps_substrate < inp.eps_end <= inp.eps_initial <= 1:
        raise ValueError("Harus berlaku: 0 < ε substrat < ε akhir ≤ ε awal ≤ 1")
    if inp.degradation_years <= 0 or inp.discount_rate_pct <= -100:
        raise ValueError("Lama degradasi harus > 0 dan tingkat diskonto > -100%")


def emissivity_at(inp: NpvInputs, mid_year: float) -> float:
    progress = min(max(mid_year / inp.degradation_years, 0.0), 1.0)
    return inp.eps_initial - (inp.eps_initial - inp.eps_end) * progress


def _npv(cash_flows: list[float], rate: float, investment: float) -> float:
    return -investment + sum(cf / (1 + rate) ** t for t, cf in enumerate(cash_flows, start=1))


def _irr(cash_flows: list[float], investment: float) -> float | None:
    low, high = IRR_BOUNDS
    if _npv(cash_flows, low, investment) * _npv(cash_flows, high, investment) > 0:
        return None
    for _ in range(IRR_ITERATIONS):
        mid = (low + high) / 2
        if _npv(cash_flows, low, investment) * _npv(cash_flows, mid, investment) <= 0:
            high = mid
        else:
            low = mid
    return (low + high) / 2


def calculate_npv(inp: NpvInputs) -> NpvResult:
    validate(inp)
    rate = inp.discount_rate_pct / 100
    span = inp.eps_initial - inp.eps_substrate
    rows, cumulative, payback = [], -inp.investment, None
    for year in range(1, inp.years + 1):
        eps = emissivity_at(inp, year - 0.5)
        factor = max(eps - inp.eps_substrate, 0.0) / span
        saving = inp.base_annual_saving * factor
        discounted = saving / (1 + rate) ** year
        if payback is None and cumulative + discounted >= 0:
            payback = year - 1 + (-cumulative / discounted)
        cumulative += discounted
        rows.append(YearRow(year, eps, factor, saving, discounted, cumulative))
    flows = [r.saving for r in rows]
    return NpvResult(tuple(rows), cumulative, _npv([inp.base_annual_saving] * inp.years, rate, inp.investment),
                     _irr(flows, inp.investment), payback)
