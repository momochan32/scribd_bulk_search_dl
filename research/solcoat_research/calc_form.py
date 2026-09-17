"""Aturan form 'Hitung dengan Asumsi' — tanpa UI agar bisa diuji.

Aturan utama: nilai yang SUDAH DIKETAHUI (dari riset atau kurs otomatis) terkunci. Nilai itu hanya boleh
diganti bila kotak 'Overwrite' pada field tersebut dicentang; bila dicentang, isian baru wajib valid.
Konstanta default mengikuti Project Instructions Solcoat v2.6.
"""

import re
from dataclasses import dataclass

from .calc_prefill import EquipmentCandidate, KnownValue
from .calculator import CalcInputs

DEFAULT_PRICE_PER_GALLON_IDR = 85_000_000
DEFAULT_OPERATING_HOURS = 8760
APP_DEFAULT_OPERATING_HOURS = 8000
SCENARIOS = (2.5, 5.0, 7.0)
SCENARIO_LABELS = ("minimum", "mostLikely", "ideal")
SCENARIO_TITLES = {"minimum": "Minimum / Konservatif", "mostLikely": "Paling Mungkin", "ideal": "Paling Ideal"}
FUEL_CHOICES = {"ng": "Gas alam (NG)", "lpg": "LPG", "fo": "Fuel oil (FO)", "refinery": "Refinery gas"}
FUEL_RATE_UNITS = ("Nm3/hr", "kg/hr")
PAYBACK_TOO_SLOW_MONTHS = 24
PAYBACK_TOO_FAST_MONTHS = 6
AUTO_CONFIDENCE = "otomatis"
VERIFIED_CONFIDENCE = "terverifikasi"
ESTIMATE_CONFIDENCE = "estimasi"
PRIMARY_CONFIDENCE = "sumber primer"


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    unit: str
    kind: str  # number | text | choice
    required: bool = False
    default: str = ""
    minimum: float | None = None
    maximum: float | None = None
    help: str = ""


FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("tag", "Tag / nama alat", "", "text", required=True),
    FieldSpec("description", "Deskripsi unit / proses", "", "text"),
    FieldSpec("fuel_type", "Jenis bahan bakar", "", "choice", required=True, default="ng"),
    FieldSpec("operation_hours", "Jam operasi per tahun", "jam", "number", required=True,
              default=str(DEFAULT_OPERATING_HOURS), minimum=1, maximum=8784,
              help="Dokumen kalkulasi Solcoat memakai 8.760; default aplikasi web 8.000."),
    FieldSpec("direct_value", "Energi bahan bakar langsung", "GJ/hr", "number", minimum=0,
              help="Prioritas 1 (paling akurat)."),
    FieldSpec("fuel_rate", "Laju bahan bakar", "", "number", minimum=0, help="Prioritas 2."),
    FieldSpec("design_duty", "Design heat duty", "GJ/hr", "number", minimum=0,
              help="Prioritas 3 — dibagi efisiensi heater."),
    FieldSpec("heater_efficiency", "Efisiensi heater", "%", "number", default="85", minimum=50, maximum=99),
    FieldSpec("actual_price", "Harga bahan bakar", "USD/MMBtu", "number", minimum=0,
              help="Kosong: aplikasi memakai fallback US$10/MMBtu (bukan angka kanon)."),
    FieldSpec("price_per_gallon", "Harga per galon", "IDR", "number", required=True,
              default=str(DEFAULT_PRICE_PER_GALLON_IDR), minimum=1, help="Material saja; default resmi Rp 85 jt."),
    FieldSpec("area_total", "Total luas area coating", "m²", "number", required=True, minimum=0.1),
    FieldSpec("fiber_share", "Porsi ceramic fiber dari total luas", "%", "number", default="0", minimum=0,
              maximum=100, help="Castable 3,50 m²/galon; ceramic fiber 2,50 m²/galon."),
    FieldSpec("usd_idr", "Kurs USD ke IDR", "IDR", "number", required=True, minimum=1),
    FieldSpec("fx_date", "Tanggal kurs", "", "text", required=True),
)
FIELD_BY_KEY = {f.key: f for f in FIELDS}


class FormError(ValueError):
    pass


@dataclass(frozen=True)
class FieldInput:
    """Kondisi satu field di layar: nilai diketahui (bila ada), status overwrite, dan teks isian."""
    key: str
    text: str
    known: KnownValue | None = None
    overwrite: bool = False


@dataclass(frozen=True)
class ResolvedValue:
    key: str
    label: str
    value: float | str | None
    unit: str
    origin: str  # riset: <sumber> | kurs otomatis | overwrite pengguna | input pengguna | default


@dataclass(frozen=True)
class FormResult:
    inputs: CalcInputs
    values: tuple[ResolvedValue, ...]
    warnings: tuple[str, ...]
    price_per_gallon_idr: float
    fuel_rate_unit: str
    fx_date: str

    def value(self, key: str) -> ResolvedValue:
        return next(v for v in self.values if v.key == key)


def is_locked(field_input: FieldInput) -> bool:
    return field_input.known is not None and not field_input.overwrite


def parse_number(text: str) -> float:
    """Menerima 85.000.000 / 85,000,000 / 1.234,5 / 1234.5 / 38,44."""
    normalized = text.strip().replace(" ", "")
    if "," in normalized and "." in normalized:
        decimal = "," if normalized.rfind(",") > normalized.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        normalized = normalized.replace(thousands, "").replace(decimal, ".")
    elif normalized.count(",") > 1 or normalized.count(".") > 1:
        normalized = normalized.replace(",", "").replace(".", "")
    elif re.fullmatch(r"-?[1-9]\d{0,2}[.,]\d{3}", normalized):
        normalized = normalized.replace(",", "").replace(".", "")  # 1.200 / 1,200 = seribu dua ratus
    elif "," in normalized:
        normalized = normalized.replace(",", ".")
    return float(normalized)


def _parse(spec: FieldSpec, text: str) -> float | str | None:
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    if spec.kind != "number":
        return cleaned
    try:
        number = parse_number(cleaned)
    except ValueError as exc:
        raise FormError(f"{spec.label}: '{cleaned}' bukan angka") from exc
    if spec.minimum is not None and number < spec.minimum:
        raise FormError(f"{spec.label}: minimal {spec.minimum:g}")
    if spec.maximum is not None and number > spec.maximum:
        raise FormError(f"{spec.label}: maksimal {spec.maximum:g}")
    return number


def resolve_field(spec: FieldSpec, field_input: FieldInput) -> ResolvedValue:
    known = field_input.known
    if known is not None and not field_input.overwrite:
        origin = {AUTO_CONFIDENCE: "kurs otomatis", VERIFIED_CONFIDENCE: f"riset terverifikasi: {known.source}",
                  ESTIMATE_CONFIDENCE: f"estimasi [A]: {known.source}",
                  PRIMARY_CONFIDENCE: f"sumber primer [U]: {known.source}"}.get(known.confidence, f"riset: {known.source}")
        return ResolvedValue(spec.key, spec.label, known.value, known.unit or spec.unit, origin)
    value = _parse(spec, field_input.text)
    if known is not None and value is None:
        raise FormError(f"{spec.label}: kotak Overwrite dicentang tetapi nilai baru belum diisi")
    if value is None and spec.default:
        return ResolvedValue(spec.key, spec.label, _parse(spec, spec.default), spec.unit, "default")
    if value is None and spec.required:
        raise FormError(f"{spec.label} wajib diisi")
    origin = "overwrite pengguna" if known is not None else "input pengguna"
    return ResolvedValue(spec.key, spec.label, value, spec.unit, origin)


def _warnings(values: dict[str, ResolvedValue], candidate: EquipmentCandidate | None) -> list[str]:
    notes = []
    if candidate and candidate.is_coal_fired:
        notes.append("Peralatan berbahan bakar batubara: skenario penghematan 2,5/5/7% TIDAK berlaku untuk boiler "
                     "batubara/PLTU (aturan Solcoat). Gunakan model avoided cost di luar kalkulator ini.")
    price = values["price_per_gallon"].value
    if price != DEFAULT_PRICE_PER_GALLON_IDR:
        price_text = f"{price:,.0f}".replace(",", ".")
        notes.append(f"Harga override Rp {price_text}/galon, default Rp 85 jt.")
    if not values["actual_price"].value:
        notes.append("Harga bahan bakar kosong: memakai fallback aplikasi US$10/MMBtu (bukan angka kanon).")
    if values["operation_hours"].value == APP_DEFAULT_OPERATING_HOURS:
        notes.append("Jam operasi 8.000 = default aplikasi web; dokumen kalkulasi Solcoat umumnya memakai 8.760.")
    if (values["fiber_share"].value or 0) > 0:
        notes.append("Substrat ceramic fiber: baseline emisivitas lebih tinggi (0,74–0,78 vs 0,50–0,59 castable), "
                     "sehingga selisih emisivitas (delta-e) hanya sekitar separuh dan manfaatnya lebih kecil.")
    if any(v.origin.startswith("estimasi") for v in values.values()):
        notes.append("Luas hasil estimasi geometri dari dimensi [A] — ganti dengan refractory schedule / GA drawing klien.")
    if any(v.origin.startswith("riset:") for v in values.values()):
        notes.append("Nilai bertanda 'riset' berasal dari ekstraksi otomatis dan belum diverifikasi ke halaman sumber.")
    return notes


def build_inputs(field_inputs: dict[str, FieldInput], fuel_rate_unit: str = "Nm3/hr",
                 candidate: EquipmentCandidate | None = None) -> FormResult:
    resolved = {spec.key: resolve_field(spec, field_inputs.get(spec.key, FieldInput(spec.key, "")))
                for spec in FIELDS}
    if resolved["fuel_type"].value not in FUEL_CHOICES:
        raise FormError(f"Jenis bahan bakar tidak dikenal: {resolved['fuel_type'].value}")
    unit = resolved["fuel_rate"].unit if resolved["fuel_rate"].origin.startswith("riset") else fuel_rate_unit
    if unit not in FUEL_RATE_UNITS:
        raise FormError(f"Satuan laju bahan bakar tidak dikenal: {unit}")

    def number(key: str) -> float:
        return float(resolved[key].value or 0)

    if not (number("direct_value") or number("fuel_rate") or number("design_duty")):
        raise FormError("Isi minimal satu basis energi: energi bahan bakar langsung, laju bahan bakar, "
                        "atau design heat duty")

    area, fiber_share = number("area_total"), number("fiber_share") / 100
    area_fiber = round(area * fiber_share, 2)
    inputs = CalcInputs(
        fuel_type=resolved["fuel_type"].value, operation_hours=number("operation_hours"),
        direct_value=number("direct_value"), direct_unit="GJ/hr",
        fuel_rate=number("fuel_rate"), fuel_rate_unit=unit,
        design_duty=number("design_duty"), design_unit="GJ/hr", heater_efficiency=number("heater_efficiency"),
        actual_price=number("actual_price"), actual_price_currency="USD", fuel_price_unit="MMBtu",
        coating_mode="estimated", coating_est_price=number("price_per_gallon"), coating_est_currency="IDR",
        area_fiber=area_fiber, area_castable=round(area - area_fiber, 2),
        scenarios=SCENARIOS, scenario_labels=SCENARIO_LABELS, exchange_rates={"USD": 1.0, "IDR": number("usd_idr")},
    )
    return FormResult(inputs=inputs, values=tuple(resolved.values()), warnings=tuple(_warnings(resolved, candidate)),
                      price_per_gallon_idr=number("price_per_gallon"), fuel_rate_unit=unit,
                      fx_date=str(resolved["fx_date"].value))


def result_warnings(result) -> list[str]:
    """Pelaporan ROI sekali saja, sesuai §Konstanta Kalkulasi butir 4."""
    notes = []
    by_label = {s.label: s for s in result.scenarios}
    if any(s.roi_percent is not None and s.roi_percent < 0 for s in result.scenarios):
        notes.append("ROI tahun pertama negatif di minimal satu skenario — ditampilkan apa adanya.")
    middle = by_label.get("mostLikely")
    if middle and middle.payback_months and middle.payback_months > PAYBACK_TOO_SLOW_MONTHS:
        notes.append("Payback skenario tengah > 24 bulan — mayoritas klien industri menolak di atas 24 bulan.")
    low = by_label.get("minimum")
    if low and low.payback_months and low.payback_months < PAYBACK_TOO_FAST_MONTHS:
        notes.append("Payback skenario konservatif < 6 bulan — terlalu bagus, periksa kembali input.")
    return notes
