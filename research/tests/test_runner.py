"""Alur tombol 'Riset Solcoat' di GUI, diuji tanpa jendela dan tanpa internet."""

import io
import threading
from pathlib import Path

import pytest

from solcoat_research import ocr_data
from solcoat_research.pipeline import ScanConfig, ScanStopped, discover_pdfs, run_scan
from solcoat_research.extract import OcrSettings
from solcoat_research.runner import default_output_dir, run_research
from test_pipeline_e2e import TEXT_PAGE, _text_pdf

FAKE_TRAINEDDATA = b"x" * ocr_data.MIN_TRAINEDDATA_BYTES


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def source(tmp_path: Path) -> Path:
    root = tmp_path / "Momo_Rescribd"
    (root / "Pupuk_Kaltim").mkdir(parents=True)
    _text_pdf(root / "Pupuk_Kaltim" / "Laporan-Kerja-Praktek-PKT_111111.pdf", TEXT_PAGE)
    return root


class TestOcrData:
    def test_download_writes_all_languages(self, tmp_path: Path):
        requested = []

        def opener(url, timeout, context):
            requested.append(url)
            return _FakeResponse(FAKE_TRAINEDDATA)

        folder = ocr_data.download_tessdata(tmp_path / "tess", opener=opener)
        assert ocr_data.is_complete(folder)
        assert [u.rsplit("/", 1)[-1] for u in requested] == ["ind.traineddata", "eng.traineddata"]

    def test_existing_files_are_not_downloaded_again(self, tmp_path: Path):
        folder = tmp_path / "tess"
        folder.mkdir()
        for lang in ocr_data.REQUIRED_LANGS:
            (folder / f"{lang}.traineddata").write_bytes(FAKE_TRAINEDDATA)
        assert ocr_data.download_tessdata(folder, opener=lambda *a, **k: pytest.fail("tidak boleh mengunduh")) == folder

    def test_truncated_download_is_rejected_and_cleaned(self, tmp_path: Path):
        with pytest.raises(RuntimeError, match="tidak lengkap"):
            ocr_data.download_tessdata(tmp_path, opener=lambda *a, **k: _FakeResponse(b"short"))
        assert not list(tmp_path.glob("*.part")) and not ocr_data.is_complete(tmp_path)

    def test_network_error_becomes_runtime_error(self, tmp_path: Path):
        def opener(*args, **kwargs):
            raise OSError("offline")

        with pytest.raises(RuntimeError, match="offline"):
            ocr_data.download_tessdata(tmp_path, opener=opener)

    def test_find_tessdata_prefers_env(self, tmp_path: Path, monkeypatch):
        for lang in ocr_data.REQUIRED_LANGS:
            (tmp_path / f"{lang}.traineddata").write_bytes(FAKE_TRAINEDDATA)
        monkeypatch.setenv("TESSDATA_PREFIX", str(tmp_path))
        assert ocr_data.find_tessdata() == tmp_path

    def test_user_dir_is_per_platform(self, monkeypatch):
        monkeypatch.setattr(ocr_data.sys, "platform", "darwin")
        assert "Application Support" in str(ocr_data.user_tessdata_dir())


class TestRunner:
    def test_default_output_is_sibling_of_source(self, source: Path):
        assert default_output_dir(source) == source.parent / "Momo_Rescribd_Riset_Solcoat"

    def test_run_without_ocr_produces_reports(self, source: Path):
        messages = []
        outputs = run_research(source, use_ocr=False, workers=1, log=messages.append)
        assert outputs.pdf.exists() and outputs.xlsx.exists() and outputs.db.exists()
        assert outputs.pdf.parent == default_output_dir(source)
        assert (outputs.documents, outputs.equipment_tier_a, outputs.ocr_used) == (1, 1, False)
        assert any("Menyusun laporan" in m for m in messages)

    def test_ocr_download_failure_falls_back_to_text_only(self, source: Path, monkeypatch):
        def fail(log):
            raise RuntimeError("Gagal mengunduh data OCR 'ind': offline")

        monkeypatch.setattr("solcoat_research.runner.ensure_tessdata", fail)
        messages = []
        outputs = run_research(source, source.parent / "out", use_ocr=True, workers=1, log=messages.append)
        assert outputs.ocr_used is False and outputs.pdf.exists()
        assert any("[PERINGATAN]" in m for m in messages)

    def test_missing_source_folder(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            run_research(tmp_path / "tidak-ada", use_ocr=False)


class TestPipelineControls:
    def test_stop_event_aborts_scan(self, source: Path, tmp_path: Path):
        stop = threading.Event()
        stop.set()
        with pytest.raises(ScanStopped):
            run_scan(ScanConfig(source, tmp_path / "out", workers=1, ocr=OcrSettings(enabled=False)),
                     log=lambda _: None, stop_event=stop)

    def test_report_folder_inside_source_is_not_scanned(self, source: Path):
        out = source / "_laporan"
        out.mkdir()
        _text_pdf(out / "Laporan_Riset_Solcoat_lama.pdf", "laporan lama")
        names = [p.name for p in discover_pdfs(source, exclude=(out,))]
        assert names == ["Laporan-Kerja-Praktek-PKT_111111.pdf"]
