"""Helper tab 'Riset Solcoat' (tanpa membuka jendela)."""

import sys
from pathlib import Path

import pytest

pytest.importorskip("customtkinter")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import research_panel  # noqa: E402


@pytest.mark.parametrize("seconds,expected", [(0, "00:00"), (5.9, "00:05"), (143, "02:23"), (3725, "1:02:05"),
                                              (-3, "00:00")])
def test_format_duration(seconds, expected):
    assert research_panel.format_duration(seconds) == expected


def test_estimate_remaining():
    assert research_panel.estimate_remaining(60, 0.25) == pytest.approx(180)
    assert research_panel.estimate_remaining(10, 0.01) is None
    assert research_panel.estimate_remaining(100, 1.0) is None
    assert research_panel.estimate_remaining(1, 0.05) is None  # terlalu dini untuk ditebak


def test_workers_are_halved_only_while_downloading(monkeypatch):
    monkeypatch.setattr(research_panel.os, "cpu_count", lambda: 10)
    assert research_panel.download_friendly_workers(True) == 5
    assert research_panel.download_friendly_workers(False) is None
    monkeypatch.setattr(research_panel.os, "cpu_count", lambda: None)
    assert research_panel.download_friendly_workers(True) == 1
