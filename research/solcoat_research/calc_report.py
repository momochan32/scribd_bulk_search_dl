"""PDF 'Hitung dengan Asumsi' — format calculation sheet kalkulator, kop band hijau Solcoat.

Sengaja TIDAK memuat bagian 'Komitmen/Garansi Performa' maupun klaim '370+ aplikasi' (keduanya masuk daftar
eskalasi prinsipal). Skenario 5% dan 7% selalu membawa kalimat kualifikasi.
"""

import re
from datetime import datetime
from pathlib import Path

from reportlab.platypus import Spacer

from .calc_form import FUEL_CHOICES, SCENARIO_TITLES, FormResult, result_warnings
from .calculator import COVERAGE_CASTABLE, COVERAGE_FIBER, GCAL_TO_GJ, MMBTU_TO_GJ, NO2_FACTOR, CalcResult
from .pdf_style import CW, H, P, callout, grid, kpirow, num, render, safe, st_body, st_c, st_cw, st_small

FOOTER = "PT SOLCOAT INDO JAYA  -  Estimasi berbasis asumsi, material saja. Bukan penawaran mengikat."
QUALIFICATION = ("Skenario 5% dan 7% adalah skenario atas yang bergantung pada kondisi operasi, bukan komitmen. "
                 "Batas yang dapat dipertahankan secara teknis untuk refraktori-saja adalah 2-4,5%; "
                 "angka konservatif 2,5% direkomendasikan bila klien meminta angka yang dapat dipertahankan.")
HIDDEN_KEYS_WITHOUT_PRICE = ("price_per_gallon",)


def _c(text):
    return P(safe(text), st_c)


def _hdr(text):
    return P(safe(text), st_cw)


def _fmt(value, digits=0) -> str:
    return "-" if value is None else num(value, digits)


def _kv_table(rows: list[tuple[str, str]]):
    return grid([[_hdr("Parameter"), _hdr("Nilai")]] + [[_c(k), _c(v)] for k, v in rows], [190, CW - 190])


def _baseline(form: FormResult, result: CalcResult) -> list:
    b, inp = result.baseline, form.inputs
    price_note = f"{_fmt(inp.actual_price, 2)} USD/MMBtu" if inp.actual_price else "fallback US$10/MMBtu (bukan kanon)"
    rows = [
        ("Jenis bahan bakar", FUEL_CHOICES.get(inp.fuel_type, inp.fuel_type)),
        ("LHV yang dipakai", f"{num(result.lhv, 3)} GJ/kg"),
        ("Basis perhitungan", result.calculation_basis),
        ("Energi masuk per jam", f"{_fmt(b.energy_gj_hr, 2)} GJ/hr  ({_fmt(b.energy_gcal_hr, 2)} Gcal/hr)"),
        ("Energi masuk tahunan", f"{_fmt(b.energy_gj)} GJ/tahun  ({_fmt(b.annual_energy_mmbtu)} MMBtu/tahun)"),
        ("Konsumsi massa tahunan", f"{_fmt(b.annual_consumption_ton)} ton/tahun"),
        ("Harga bahan bakar", price_note),
        ("Biaya energi tahunan", f"US$ {_fmt(b.cost_usd)}  /  Rp {_fmt(b.costs.get('IDR'))}"),
    ]
    return [H("2 - Data Baseline"), _kv_table(rows)]


def _investment(form: FormResult, result: CalcResult, show_price: bool) -> list:
    inp = form.inputs
    rows = [
        ("Luas castable / brick", f"{_fmt(inp.area_castable, 1)} m²  ->  {result.gallons_castable} galon "
                                  f"({str(COVERAGE_CASTABLE).replace('.', ',')} m²/galon)"),
        ("Luas ceramic fiber", f"{_fmt(inp.area_fiber, 1)} m²  ->  {result.gallons_fiber} galon "
                               f"({str(COVERAGE_FIBER).replace('.', ',')} m²/galon)"),
        ("Total galon (dibulatkan ke atas per substrat)", f"{_fmt(result.gallons_total)} galon"),
    ]
    if show_price:
        rows.append(("Harga per galon", f"Rp {_fmt(form.price_per_gallon_idr)}"))
    rows += [("Total investasi material", f"Rp {_fmt(result.total_coating_cost_usd * inp.exchange_rates['IDR'])}"),
             ("Total investasi material (USD)", f"US$ {_fmt(result.total_coating_cost_usd)}")]
    return [H("3 - Data Biaya & Investasi"), _kv_table(rows),
            P("* Nilai investasi hanya untuk material; biaya aplikasi/jasa tidak termasuk.", st_small)]


def _pct(value: float) -> str:
    return f"{value:g}".replace(".", ",") + "%"


def _scenarios(form: FormResult, result: CalcResult) -> list:
    rate = form.inputs.exchange_rates["IDR"]
    rows = [[_hdr(h) for h in ("%", "Skenario", "Energi hemat (GJ/th)", "MMBtu/th", "Hemat (US$/th)",
                               "Hemat (Rp/th)", "CO2 (ton)", "ROI (%)", "Payback (bln)")]]
    for sc in result.scenarios:
        rows.append([_c(_pct(sc.percentage)), _c(SCENARIO_TITLES.get(sc.label, sc.label or "-")),
                     _c(_fmt(sc.energy_saving_gj)), _c(_fmt(sc.energy_saving_mmbtu)), _c(_fmt(sc.financial_saving_usd)),
                     _c(_fmt(sc.financial_saving_usd * rate)), _c(_fmt(sc.co2_red, 1)),
                     _c(_fmt(sc.roi_percent)), _c(_fmt(sc.payback_months, 1))])
    widths = [30, 74, 62, 52, 60, 76, 46, 42]
    return [H("4 - Hasil Estimasi (klaim vendor [V])"), grid(rows, widths + [CW - sum(widths)]), Spacer(1, 3),
            P(QUALIFICATION, st_small)]


def _shown_value(key: str, value) -> str:
    if key == "fuel_type":
        return FUEL_CHOICES.get(value, str(value))
    if isinstance(value, float):
        return num(value, 0) if value.is_integer() else num(value, 2)
    return str(value) if value not in (None, "") else "-"


def _sources(form: FormResult, result: CalcResult, show_price: bool) -> list:
    rows = [[_hdr("Input"), _hdr("Nilai dipakai"), _hdr("Asal nilai")]]
    for v in form.values:
        if not show_price and v.key in HIDDEN_KEYS_WITHOUT_PRICE:
            continue
        unit = (form.fuel_rate_unit if v.key == "fuel_rate" else v.unit) if v.value not in (None, "", 0) else ""
        rows.append([_c(v.label), _c(f"{_shown_value(v.key, v.value)} {unit}".strip()), _c(v.origin)])
    notes = list(form.warnings) + result_warnings(result)
    flow = [H("5 - Asumsi, Sumber Nilai & Catatan"), grid(rows, [150, 120, CW - 270]), Spacer(1, 4)]
    flow += [P(f"- {safe(a)}", st_body) for a in result.assumptions]
    if notes:
        flow += [Spacer(1, 4), callout("<br/>".join(f"- {safe(n)}" for n in notes))]
    constants = (f"Konstanta: 1 MMBtu = {MMBTU_TO_GJ} GJ | 1 Gcal = {GCAL_TO_GJ} GJ | CO2 = {result.co2_factor:.4f} ton/GJ"
                 f" | NO2 = {NO2_FACTOR} ton/GJ | Kurs: 1 USD = Rp {_fmt(form.inputs.exchange_rates['IDR'])} "
                 f"per {form.fx_date}")
    return flow + [Spacer(1, 4), P(safe(constants), st_small),
                   P("Rumus: port Python dari calculate.solcoat.com (src/utils/calc.js), diuji setara angka per angka.",
                     st_small)]


def default_filename(form: FormResult, now: datetime | None = None) -> str:
    tag = re.sub(r"[^\w-]+", "_", str(form.value("tag").value)).strip("_")[:40] or "ALAT"
    return f"Solcoat_Calculation_{tag}_ASUMSI_{(now or datetime.now()):%Y%m%d_%H%M}.pdf"


def build_calc_pdf(form: FormResult, result: CalcResult, path: Path, show_price_per_gallon: bool = False,
                   now: datetime | None = None) -> Path:
    now = now or datetime.now()
    tag = str(form.value("tag").value)
    description = str(form.value("description").value or "-")
    middle = next((s for s in result.scenarios if s.label == "mostLikely"), None)
    rate = form.inputs.exchange_rates["IDR"]
    flow = [
        kpirow([
            (num(form.inputs.area_castable + form.inputs.area_fiber), "m² total luas coating"),
            (num(result.gallons_total), "galon (bulat ke atas)"),
            (f"Rp {num(result.total_coating_cost_usd * rate / 1e9, 2)} M", "investasi material"),
            (_fmt(middle.payback_months, 1) if middle else "-", "bulan payback skenario 5%"),
        ]),
        Spacer(1, 6),
        H("1 - Identifikasi Furnace"),
        _kv_table([("Tag furnace", tag), ("Deskripsi unit / proses", description),
                   ("Jam operasi", f"{_fmt(form.inputs.operation_hours)} jam/tahun")]),
    ]
    flow += _baseline(form, result) + _investment(form, result, show_price_per_gallon)
    flow += _scenarios(form, result) + _sources(form, result, show_price_per_gallon)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    render(path, hdr_r=f"{now:%d/%m/%Y}  -  {tag[:30]}  -  ASUMSI",
           band=f"{description[:80]}  -  Kalkulasi dengan asumsi",
           title=safe(f"Estimasi Penghematan Energi - {tag}"),
           subtitle=safe("Solcoat High Emissivity Coating - dihitung dengan asumsi pengguna, rumus calculate.solcoat.com"),
           flow=flow, footer=FOOTER)
    return Path(path)
