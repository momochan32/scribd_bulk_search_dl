"""Kinerja unit PLTU PLN Nusantara Power 2025 — salinan §5 file kanon 15-data-pln-np-2025.md (status [U]).

Bila Laporan Tahunan 2026 terbit, perbarui tabel ini DAN file kanon. Unit di luar PLN NP (Suralaya, Paiton 3/7/8,
IPP) tidak ada di sini dan kinerjanya wajib diisi manual dari data unit — asumsi EAF 85% dilarang.
"""

from dataclasses import dataclass

SOURCE = ("Laporan Tahunan 2025 PT PLN Nusantara Power, tabel kinerja Unit Pembangkitan Batubara, "
          "halaman 274, 277, 280-281, 284, 291, dan 301")
MANUAL_UNIT = "Unit di luar PLN NP (isi manual)"
FORBIDDEN_EAF_ASSUMPTION = 85.0


@dataclass(frozen=True)
class UnitPerformance:
    dtp_mw: float
    eaf: float
    sof: float | None
    efor: float
    nphr: float
    production_gwh: float | None


FLEET = UnitPerformance(6239.50, 86.86, 10.90, 1.92, 3196.43, 36336.07)

UNITS: dict[str, UnitPerformance] = {
    "UP Paiton": UnitPerformance(1460, 92.29, 7.35, 0.38, 2888.97, 8857.12),
    "UP Indramayu": UnitPerformance(990, 85.25, 11.91, 2.12, 3096.12, 6084.21),
    "UP Rembang": UnitPerformance(630, 88.91, 8.99, 1.13, 3065.11, 4058.34),
    "UP Pacitan": UnitPerformance(630, 84.11, 14.20, 1.88, 2946.65, 3813.55),
    "UP Tanjung Awar-Awar": UnitPerformance(700, 87.17, 11.12, 1.52, 2822.47, 4664.65),
    "UP Tenayan": UnitPerformance(220, 84.70, 13.06, 2.09, 3794.91, 1271.06),
    "UP Kaltim Teluk": UnitPerformance(220, 81.62, 13.53, 4.04, 3509.30, 1146.77),
    "UP Pulang Pisau": UnitPerformance(120, 83.64, 13.99, 2.73, 3956.67, 687.61),
    "UP Bukit Asam": UnitPerformance(260, 93.87, 4.50, 3.29, 3837.48, 669.61),
    "UP Sebalang": UnitPerformance(200, 78.84, 15.01, 7.05, 4710.81, 928.30),
    "UP Tarahan": UnitPerformance(200, 76.08, 18.06, 5.23, 3212.48, 1123.42),
    "UP Nagan Raya": UnitPerformance(220, 80.93, 18.16, 1.01, 4831.73, 677.17),
    "UP Punagaya": UnitPerformance(220, 81.37, 10.79, 4.85, 4396.47, 1491.29),
    "PLTU Tembilahan": UnitPerformance(14, 85.42, 13.40, 1.37, 6156.83, 92.19),
    "PLTU Ketapang": UnitPerformance(20, 83.96, 13.42, 2.99, 6232.64, 135.33),
    "PLTU Amurang": UnitPerformance(50, 87.64, 10.98, 1.51, 4663.35, 243.79),
    "PLTU Anggrek": UnitPerformance(55, 78.05, 13.56, 9.64, 5980.36, 213.32),
    "PLTU Ampana": UnitPerformance(6.5, 81.36, None, 1.62, 9077.30, 26.77),
    "PLTU Kendari 1-2": UnitPerformance(24, 80.39, None, 6.75, 5673.50, None),
}

UNIT_NOTES = {
    "UP Paiton": "Angka UP Paiton gabungan 2x400 MW + Paiton 9 (660 MW) sejak 2023 — bukan angka Paiton 9 sendiri.",
    "UP Nagan Raya": "Prospek tertinggi: SOF 18,16% dan boiler CFB (porsi refraktori ±40%).",
    "UP Tarahan": "Prospek tertinggi: EAF terendah armada 76,08%, SOF 18,06%.",
}
