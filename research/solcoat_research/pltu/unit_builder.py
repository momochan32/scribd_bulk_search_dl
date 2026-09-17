"""Isian form Mode PLTU → dict UNIT untuk engine.build(), plus checklist §5 format laporan PLTU.

Template sengaja generik: teks khusus unit lain (mis. Paiton 9) tidak boleh terbawa ke dokumen klien lain.
Semua interval penggantian dan faktor keterkaitan berstatus asumsi kerja [A].
"""

import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import engine
from .pln_data import FORBIDDEN_EAF_ASSUMPTION, UNITS as PLN_UNITS
from .pln_data import SOURCE as PLN_SOURCE

DEFAULT_PRICE_PER_GALLON = 85_000_000
PC_AREA_WARNING_M2 = 1000
REDUCTION_FOR_SENSITIVITY = 0.30

WATERWALL_ROW = ("Membrane waterwall envelope furnace", "di atas 500 C",
                 "Belum dapat dikuotasi: konduktivitas termal coating matang dan DFT pada tube belum dikonfirmasi prinsipal")
DEFAULT_MECHANISMS = (
    ("Pengurangan clinker",
     "Abu leleh meresap ke pori refraktori, membeku, lalu terkunci secara mekanis. Lapisan yang menutup pori "
     "menghalangi peresapan itu", "Ketebalan deposit dan jumlah clinker per meter persegi pada inspeksi outage"),
    ("Pembersihan lebih jarang", "Deposit yang lebih tipis dan tidak mengunci lebih mudah lepas dengan sendirinya",
     "Frekuensi dan durasi penghentian pembersihan dari catatan outage"),
    ("Umur lining lebih panjang", "Lapisan melindungi castable di bawahnya dari abrasi partikel dan serangan gas panas",
     "Interval penggantian lining burner throat dan arch"),
    ("Erosi dinding logam melambat", "Proteksi permukaan mengurangi laju penipisan dinding",
     "Hasil pengukuran ketebalan dinding pada inspeksi ultrasonik"),
)
DEFAULT_NOT_COUNTED = (
    "Komponen yang tidak dihitung sebagai manfaat: elemen air preheater cold, intermediate, dan hot; grinding roll, "
    "grinding table, dan deflector pulverizer; elbow coal pipe; air mix damper dan ducting fan. Seluruhnya tidak "
    "memiliki keterkaitan dengan permukaan yang dilapisi atau bekerja di bawah suhu curing coating.")
DEFAULT_STREAMS_TEXT = (
    "Jam kerja pembersihan manual deposit | 480 jam-orang per tahun x Rp 250.000 per jam-orang [A] | 120000000 | tidak\n"
    "Coal Nozzle Burner Assembly | Rp 1.200.000.000 per set - interval 3 tahun - faktor keterkaitan 0,30 [A] | 120000000 | ya")
DEFAULT_AREA_SOURCE = ("Estimasi teknik [A]. Akan digantikan angka sebenarnya setelah GA drawing dan refractory "
                       "schedule tersedia")


class PltuFormError(ValueError):
    pass


@dataclass(frozen=True)
class Zone:
    name: str
    area_m2: float


@dataclass(frozen=True)
class Stream:
    name: str
    basis: str
    annual_value: float
    scales_with_interval: bool = True


@dataclass(frozen=True)
class Performance:
    eaf: float
    sof: float | None
    efor: float
    nphr: float
    production_gwh: float | None
    dtp_mw: float
    overwritten: bool = False


@dataclass(frozen=True)
class PltuInputs:
    tag: str
    rev: str
    client: str
    asset_name: str
    location: str
    up: str
    capacity_mw: float
    boiler_class: str  # PC | CFB
    oem: str
    cod: str
    performance: Performance
    castable_zones: tuple[Zone, ...]
    fiber_zones: tuple[Zone, ...]
    streams: tuple[Stream, ...]
    interval_label: str
    component_price_source: str
    unit_spec_source: str
    area_source: str = DEFAULT_AREA_SOURCE
    price_per_gallon: float = DEFAULT_PRICE_PER_GALLON
    gallon_override: int | None = None
    show_price_per_gallon: bool = False
    not_counted: str = DEFAULT_NOT_COUNTED


def id_num(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _number(text: str, what: str) -> float:
    cleaned = text.strip().replace(" ", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", cleaned):
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError as exc:
        raise PltuFormError(f"{what}: '{text.strip()}' bukan angka") from exc


def parse_zones(text: str, substrate: str) -> tuple[Zone, ...]:
    """Satu zona per baris: 'Nama zona ; luas m2'."""
    zones = []
    for line_no, line in enumerate((ln for ln in text.splitlines() if ln.strip()), start=1):
        if ";" not in line:
            raise PltuFormError(f"Zona {substrate} baris {line_no}: format 'Nama zona ; luas'")
        name, area = (part.strip() for part in line.rsplit(";", 1))
        value = _number(area, f"Zona {substrate} baris {line_no}")
        if not name or value <= 0:
            raise PltuFormError(f"Zona {substrate} baris {line_no}: nama wajib diisi dan luas harus > 0")
        zones.append(Zone(name, value))
    return tuple(zones)


def parse_streams(text: str) -> tuple[Stream, ...]:
    """Satu aliran per baris: 'Nama | dasar perhitungan | nilai tahunan Rp | ya/tidak (ikut skala interval)'."""
    streams = []
    for line_no, line in enumerate((ln for ln in text.splitlines() if ln.strip()), start=1):
        parts = [p.strip() for p in line.split("|")]
        if len(parts) not in (3, 4) or not parts[0] or not parts[1]:
            raise PltuFormError(f"Aliran perawatan baris {line_no}: format 'Nama | dasar | nilai | ya/tidak'")
        scales = parts[3].lower() not in ("tidak", "no", "false", "0") if len(parts) == 4 else True
        value = _number(parts[2], f"Aliran perawatan baris {line_no}")
        if value <= 0:
            raise PltuFormError(f"Aliran perawatan baris {line_no}: nilai tahunan harus > 0")
        streams.append(Stream(parts[0], parts[1], value, scales))
    return tuple(streams)


def lining_stream(area_m2: float, thickness_m: float, interval_years: float, density: float = 2400,
                  price_per_kg: float = 20_000, installed_factor: float = 2.5) -> Stream:
    """Sama dengan helper lining() di unit_paiton9.py agar aritmatika konsisten antar dokumen."""
    if min(area_m2, thickness_m, interval_years) <= 0:
        raise PltuFormError("Lining: luas, tebal, dan interval harus > 0")
    tons = area_m2 * thickness_m * density / 1000
    installed = tons * 1000 * price_per_kg * installed_factor
    basis = (f"{id_num(area_m2, 0)} m2 x tebal {id_num(thickness_m, 3)} m x densitas {id_num(density, 0)} kg/m3 = "
             f"{id_num(tons)} ton - material Rp {id_num(price_per_kg, 0)} per kg - faktor terpasang "
             f"x{id_num(installed_factor, 1)} termasuk jasa, anchor, dan curing - interval "
             f"{id_num(interval_years, 0)} tahun [A]")
    return Stream("Lining refraktori burner throat dan arch", basis, installed / interval_years, True)


def scale_intervals(label: str, factor: int) -> str:
    return re.sub(r"(\d+(?:[.,]\d+)?)\s*tahun",
                  lambda m: f"{id_num(float(m.group(1).replace(',', '.')) * factor, 0)} tahun", label)


def summary(inputs: PltuInputs) -> dict:
    """Angka utama yang sama dengan engine.build(), untuk ditampilkan sebelum PDF dibuat."""
    cast = sum(z.area_m2 for z in inputs.castable_zones)
    fib = sum(z.area_m2 for z in inputs.fiber_zones)
    gallons = inputs.gallon_override or (math.ceil(cast / engine.COV_CAST / 10) * 10 +
                                         math.ceil(fib / engine.COV_FIB / 10) * 10)
    investment = gallons * inputs.price_per_gallon
    maintenance = sum(s.annual_value for s in inputs.streams)
    lost = inputs.capacity_mw * engine.JAM * (1 - inputs.performance.eaf / 100)
    production_low = lost * engine.SHARE_DEPOSIT * engine.NILAI_BAWAH
    benefit_30 = (maintenance + production_low) * REDUCTION_FOR_SENSITIVITY
    return {"area_m2": cast + fib, "castable_m2": cast, "fiber_m2": fib, "gallons": gallons, "investment": investment,
            "maintenance": maintenance, "production_low": production_low,
            "payback_30_months": investment / benefit_30 * 12 if benefit_30 > 0 else None}


def checklist(inputs: PltuInputs) -> tuple[list[str], list[str]]:
    """(errors, warnings) — errors memblokir pembuatan PDF."""
    required = {"Tag unit": inputs.tag, "Revisi": inputs.rev, "Klien": inputs.client, "Nama aset": inputs.asset_name,
                "Ringkasan interval": inputs.interval_label, "Sumber harga komponen": inputs.component_price_source,
                "Sumber spesifikasi unit": inputs.unit_spec_source}
    errors = [f"{name} wajib diisi" for name, value in required.items() if not str(value).strip()]
    if inputs.capacity_mw <= 0:
        errors.append("Kapasitas unit (MW) harus > 0")
    if not (inputs.castable_zones or inputs.fiber_zones):
        errors.append("Minimal satu zona hot face (castable atau ceramic fiber)")
    if not inputs.streams:
        errors.append("Minimal satu aliran biaya perawatan yang dihindari")
    if not 0 < inputs.performance.eaf < 100:
        errors.append("EAF harus di antara 0 dan 100%")
    if inputs.boiler_class not in ("PC", "CFB"):
        errors.append("Kelas boiler harus PC atau CFB")
    return errors, ([] if errors else _warnings(inputs))


def _warnings(inputs: PltuInputs) -> list[str]:
    stats = summary(inputs)
    warnings = []
    if inputs.boiler_class == "PC" and stats["area_m2"] > PC_AREA_WARNING_M2:
        warnings.append(f"Boiler PC dengan {id_num(stats['area_m2'], 0)} m2: area PC biasanya ratusan m2 — periksa "
                        "apakah waterwall ikut terhitung.")
    if inputs.boiler_class == "PC":
        warnings.append("Boiler PC: porsi refraktori ±5–8,6%, nilainya kecil secara struktural. CFB adalah segmen utama.")
    if inputs.performance.eaf == FORBIDDEN_EAF_ASSUMPTION:
        warnings.append("EAF 85% adalah asumsi yang dilarang — pakai EAF aktual unit.")
    if inputs.performance.overwritten:
        warnings.append("Data kinerja PLN di-overwrite pengguna — sumbernya dicatat di Bagian 9.")
    if inputs.price_per_gallon != DEFAULT_PRICE_PER_GALLON:
        warnings.append(f"Harga override Rp {id_num(inputs.price_per_gallon, 0)}/galon, default Rp 85 jt.")
    if inputs.up == "UP Paiton":
        warnings.append("Angka UP Paiton adalah gabungan unit — bukan angka Paiton 9 sendiri.")
    if stats["payback_30_months"] and stats["payback_30_months"] > 24:
        warnings.append("Payback skenario 30% > 24 bulan — normal untuk PLTU; ditampilkan apa adanya.")
    return warnings


def output_filename(inputs: PltuInputs) -> str:
    def safe(text: str) -> str:
        return re.sub(r"[^\w-]+", "_", text).strip("_")
    return f"Solcoat_Calculation_{safe(inputs.tag).upper()}_KLIEN_{safe(inputs.rev)}.pdf"


def _illustration(streams: tuple[Stream, ...]) -> str:
    scaled = next((s for s in streams if s.scales_with_interval), None)
    if scaled is None:
        return "Seluruh aliran pada Bagian 5 tidak bergantung pada interval penggantian."
    base = scaled.annual_value
    return (f"Ilustrasi pada aliran {scaled.name.lower()}, dengan reduksi 30% yang sama pada kedua kasus. Pada interval "
            f"saat ini beban tahunannya Rp {id_num(base, 0)} dan manfaat yang dapat diklaim Rp {id_num(base * 0.3, 0)} "
            f"per tahun. Bila penggantian empat kali lebih jarang, beban tahunannya Rp {id_num(base / 4, 0)} dan "
            f"manfaat yang dapat diklaim Rp {id_num(base * 0.3 / 4, 0)} per tahun. Coating bekerja sama efektifnya; "
            "yang berbeda adalah besaran beban yang tersedia untuk dikurangi.")


def _sources(inputs: PltuInputs, stats: dict) -> list[tuple[str, str, str]]:
    p = inputs.performance
    performance_source = PLN_SOURCE if inputs.up in PLN_UNITS else "Data kinerja unit dari klien"
    if p.overwritten:
        performance_source += "; sebagian nilai diganti pengguna"
    return [
        ("EAF, SOF, EFOR, NPHR, produksi tenaga listrik, dan daya terpasang",
         f"EAF {id_num(p.eaf)}% - SOF {id_num(p.sof)}% - EFOR {id_num(p.efor)}% - NPHR {id_num(p.nphr)} kCal/kWh - "
         f"produksi {id_num(p.production_gwh)} GWh - DTP {id_num(p.dtp_mw, 0)} MW", performance_source),
        ("Biaya Pokok Penyediaan pembangkit", "Rp 1.283,23 per kWh",
         "Laporan Tahunan 2025 PT PLN Nusantara Power, tabel capaian Key Performance Indicator korporat, halaman 399"),
        ("Harga batu bara dan biaya bahan bakar", "Rp 953.995 per ton - Rp 661,80 per kWh",
         "Laporan Tahunan 2025 PT PLN Nusantara Power, Catatan 21 Beban Bahan Bakar dan Pelumas halaman 961, "
         "dibagi konsumsi batu bara pada halaman 299"),
        ("Nilai energi pengganti", "Rp 289.000 sampai Rp 621.000 per MWh",
         "Selisih Biaya Pokok Penyediaan terhadap biaya bahan bakar pembangkit batu bara, dihitung dari sumber di atas"),
        ("Harga komponen", "Lihat dasar perhitungan Bagian 5", inputs.component_price_source),
        ("Porsi kehilangan produksi akibat deposisi abu", "2,5%",
         "Analisis basis data NERC Generating Availability Data System periode 1995 sampai 2004, dipublikasikan "
         "dalam Fuel Processing Technology volume 88 tahun 2007"),
        ("Spesifikasi unit", f"{id_num(inputs.capacity_mw, 0)} MW, {inputs.boiler_class}, OEM {inputs.oem or '—'}",
         inputs.unit_spec_source),
        ("Coverage rate dan batas suhu curing",
         "Castable 3,50 m2 per galon - ceramic fiber 2,50 m2 per galon - curing di atas 500 derajat C",
         "Spesifikasi teknis SOLCOAT High Emissivity Coating, Solcoat Industries"),
        ("Luas per zona hot face", f"{id_num(stats['area_m2'], 0)} m2", inputs.area_source),
        ("Interval penggantian komponen dan faktor keterkaitan", re.sub(r"<[^>]+>", "", inputs.interval_label),
         "Asumsi kerja Solcoat [A]. Daftar harga memuat harga satuan tanpa interval penggantian, sehingga interval "
         "disusun untuk mengubah harga per set menjadi nilai per tahun. Akan digantikan riwayat overhaul unit"),
    ]


def _engine_area(value: float) -> float | int:
    """Engine mencetak luas apa adanya; 420 lebih rapi daripada 420.0."""
    return int(value) if float(value).is_integer() else round(value, 1)


def build_unit(inputs: PltuInputs, output_dir: Path, today: date | None = None) -> dict:
    errors, _ = checklist(inputs)
    if errors:
        raise PltuFormError("; ".join(errors))
    today = today or date.today()
    stats, p = summary(inputs), inputs.performance
    unit = dict(
        out=str(Path(output_dir) / output_filename(inputs)), tag=inputs.tag.upper(), rev=inputs.rev,
        tanggal=f"{today:%d/%m/%Y}", klien=inputs.client, nama_aset=inputs.asset_name,
        up=inputs.up if inputs.up in PLN_UNITS else inputs.asset_name, h1=inputs.asset_name,
        h2=f"Boiler {inputs.boiler_class} {id_num(inputs.capacity_mw, 0)} MW - Perhitungan Biaya Perawatan yang "
           "Dihindari atas Seluruh Area Berlining Refraktori",
        harga_gal=inputs.price_per_gallon, tampilkan_harga_galon=inputs.show_price_per_gallon,
        mw=inputs.capacity_mw, eaf=p.eaf, eaf_s=id_num(p.eaf), sof=id_num(p.sof), efor=id_num(p.efor),
        nphr=id_num(p.nphr), prod_gwh=id_num(p.production_gwh), dtp=id_num(p.dtp_mw, 0),
        ident=[("Tag unit", inputs.tag.upper()), ("Nama aset", inputs.asset_name),
               ("Pemilik dan operator", inputs.client), ("Lokasi", inputs.location or "—"),
               ("Kapasitas terpasang", f"{id_num(inputs.capacity_mw, 0)} MW"), ("Kelas boiler", inputs.boiler_class),
               ("OEM boiler", inputs.oem or "—"), ("COD", inputs.cod or "—"), ("Jam operasi", "8.760 jam per tahun")],
        cast=[(z.name, _engine_area(z.area_m2)) for z in inputs.castable_zones],
        fib=[(z.name, _engine_area(z.area_m2)) for z in inputs.fiber_zones],
        zona_luar=[WATERWALL_ROW] + list(engine.ZONA_LUAR_DEFAULT),
        mekanisme=list(DEFAULT_MECHANISMS),
        streams=[dict(nama=s.name, dasar=s.basis, nilai=s.annual_value, skala_interval=s.scales_with_interval)
                 for s in inputs.streams],
        tidak_dihitung=inputs.not_counted,
        interval_label=f"<b>{inputs.interval_label}</b><br/>Angka yang dipakai pada Bagian 5",
        interval_2x=scale_intervals(inputs.interval_label, 2),
        interval_4x=scale_intervals(inputs.interval_label, 4),
        ilustrasi_interval=_illustration(inputs.streams),
        sumber=_sources(inputs, stats),
    )
    if inputs.gallon_override:
        unit["galon_override"] = inputs.gallon_override
    return unit


def generate_pdf(inputs: PltuInputs, output_dir: Path, today: date | None = None) -> Path:
    unit = build_unit(inputs, output_dir, today)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    engine.build(unit)
    return Path(unit["out"])
