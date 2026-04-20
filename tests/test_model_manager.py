"""Tests for the plate-detector model variant registry and path resolver.

Covers §2 of the `plate-detector-larger-model` change: a registry keyed on
`"n" | "s" | "m"` drives `get_model_path(variant)` and (in §3) `download_model`.
The `"n"` entry preserves the pre-change URL and cache filename so that existing
users experience zero regression.
"""

from __future__ import annotations

import pytest

from trailvideocut.plate import model_manager


# The canonical URLs and filenames each variant must resolve to. Kept inline
# rather than imported from the module so the tests pin the contract instead
# of following the implementation.
_EXPECTED_N_URL = (
    "https://huggingface.co/ml-debi/yolov8-license-plate-detection"
    "/resolve/main/best.onnx"
)
_EXPECTED_N_FILENAME = "plate_detector_yolov8n.onnx"
_EXPECTED_S_URL = (
    "https://huggingface.co/morsetechlab/yolov11-license-plate-detection"
    "/resolve/main/license-plate-finetune-v1s.onnx"
)
_EXPECTED_S_FILENAME = "plate_detector_yolov11s.onnx"
_EXPECTED_M_URL = (
    "https://huggingface.co/morsetechlab/yolov11-license-plate-detection"
    "/resolve/main/license-plate-finetune-v1m.onnx"
)
_EXPECTED_M_FILENAME = "plate_detector_yolov11m.onnx"


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """Redirect `get_cache_dir` to an empty tmp directory per test."""
    monkeypatch.setattr(model_manager, "get_cache_dir", lambda: tmp_path)
    return tmp_path


class TestVariantsRegistry:
    """§2.1 — the _VARIANTS registry shape and content."""

    def test_keys_are_n_s_m(self):
        assert set(model_manager._VARIANTS.keys()) == {"n", "s", "m"}

    def test_n_entry_preserves_pre_change_values(self):
        url, filename = model_manager._VARIANTS["n"]
        assert url == _EXPECTED_N_URL
        assert filename == _EXPECTED_N_FILENAME

    def test_s_entry_points_at_morsetechlab_v11s(self):
        url, filename = model_manager._VARIANTS["s"]
        assert url == _EXPECTED_S_URL
        assert filename == _EXPECTED_S_FILENAME

    def test_m_entry_points_at_morsetechlab_v11m(self):
        url, filename = model_manager._VARIANTS["m"]
        assert url == _EXPECTED_M_URL
        assert filename == _EXPECTED_M_FILENAME


class TestGetModelPathVariant:
    """§2.2 — variant-aware resolution against the cache directory."""

    def test_n_returns_none_when_missing(self, isolated_cache):
        assert model_manager.get_model_path("n") is None

    def test_n_returns_path_when_present(self, isolated_cache):
        (isolated_cache / _EXPECTED_N_FILENAME).write_bytes(b"")
        assert model_manager.get_model_path("n") == isolated_cache / _EXPECTED_N_FILENAME

    def test_s_returns_path_when_present(self, isolated_cache):
        (isolated_cache / _EXPECTED_S_FILENAME).write_bytes(b"")
        assert model_manager.get_model_path("s") == isolated_cache / _EXPECTED_S_FILENAME

    def test_s_returns_none_when_missing(self, isolated_cache):
        assert model_manager.get_model_path("s") is None

    def test_m_returns_path_when_present(self, isolated_cache):
        (isolated_cache / _EXPECTED_M_FILENAME).write_bytes(b"")
        assert model_manager.get_model_path("m") == isolated_cache / _EXPECTED_M_FILENAME

    def test_m_returns_none_when_missing(self, isolated_cache):
        assert model_manager.get_model_path("m") is None

    def test_variants_have_isolated_filenames(self, isolated_cache):
        """Writing the n cache file does not accidentally satisfy s or m."""
        (isolated_cache / _EXPECTED_N_FILENAME).write_bytes(b"")
        assert model_manager.get_model_path("n") is not None
        assert model_manager.get_model_path("s") is None
        assert model_manager.get_model_path("m") is None


class TestGetModelPathRejectsUnknownVariant:
    """§2.3 — unknown variant strings raise ValueError naming the supported set."""

    def test_bogus_raises_value_error(self, isolated_cache):
        with pytest.raises(ValueError) as exc_info:
            model_manager.get_model_path("bogus")
        msg = str(exc_info.value)
        # Message must name the supported variants so the caller knows what to fix.
        assert "n" in msg and "s" in msg and "m" in msg

    def test_empty_string_raises_value_error(self, isolated_cache):
        with pytest.raises(ValueError):
            model_manager.get_model_path("")

    def test_uppercase_rejected(self, isolated_cache):
        """Variant keys are case-sensitive by design."""
        with pytest.raises(ValueError):
            model_manager.get_model_path("N")


class TestGetModelPathDefaultArg:
    """Zero-arg call resolves to the default variant ("m")."""

    def test_no_arg_matches_m_when_missing(self, isolated_cache):
        assert model_manager.get_model_path() == model_manager.get_model_path("m")
        assert model_manager.get_model_path() is None

    def test_no_arg_matches_m_when_present(self, isolated_cache):
        (isolated_cache / _EXPECTED_M_FILENAME).write_bytes(b"")
        assert model_manager.get_model_path() == isolated_cache / _EXPECTED_M_FILENAME
        assert model_manager.get_model_path() == model_manager.get_model_path("m")


class _FakeResponse:
    """Minimal `urllib.request.urlopen` stand-in that streams fixed chunks."""

    def __init__(self, chunks: list[bytes], total: int | None = None):
        self._chunks = list(chunks)
        total_len = sum(len(c) for c in chunks) if total is None else total
        self.headers = {"Content-Length": str(total_len)}

    def read(self, _size: int = -1) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


class TestDownloadModelVariant:
    """§3 — download_model is variant-aware and variant-isolated."""

    def test_s_writes_to_v11s_filename_and_reports_progress(
        self, isolated_cache, monkeypatch,
    ):
        # §3.1
        captured_urls: list[str] = []

        def fake_urlopen(url, timeout=0):
            captured_urls.append(url)
            return _FakeResponse([b"AAAA", b"BBBB"])

        monkeypatch.setattr(
            "trailvideocut.plate.model_manager.urllib.request.urlopen",
            fake_urlopen,
        )
        progress: list[tuple[int, int]] = []
        result = model_manager.download_model(
            "s",
            progress_callback=lambda d, t: progress.append((d, t)),
        )
        assert result == isolated_cache / _EXPECTED_S_FILENAME
        assert result.exists()
        assert captured_urls == [_EXPECTED_S_URL]
        assert progress  # at least one callback
        # Final progress should reach the total reported by Content-Length.
        final_downloaded, total = progress[-1]
        assert final_downloaded == 8
        assert total == 8

    def test_n_writes_to_v8n_filename_with_unchanged_url(
        self, isolated_cache, monkeypatch,
    ):
        # §3.2 — default variant must not regress.
        captured_urls: list[str] = []

        def fake_urlopen(url, timeout=0):
            captured_urls.append(url)
            return _FakeResponse([b"NN"])

        monkeypatch.setattr(
            "trailvideocut.plate.model_manager.urllib.request.urlopen",
            fake_urlopen,
        )
        result = model_manager.download_model("n")
        assert result == isolated_cache / _EXPECTED_N_FILENAME
        assert captured_urls == [_EXPECTED_N_URL]

    def test_no_op_when_variant_file_already_cached(
        self, isolated_cache, monkeypatch,
    ):
        # §3.3 — cache hit must not trigger a network call.
        (isolated_cache / _EXPECTED_M_FILENAME).write_bytes(b"already-here")

        def fail_urlopen(*args, **kwargs):
            raise AssertionError("urlopen was called despite cache hit")

        monkeypatch.setattr(
            "trailvideocut.plate.model_manager.urllib.request.urlopen",
            fail_urlopen,
        )
        result = model_manager.download_model("m")
        assert result == isolated_cache / _EXPECTED_M_FILENAME
        assert result.read_bytes() == b"already-here"  # untouched

    def test_bogus_variant_raises_before_network_call(
        self, isolated_cache, monkeypatch,
    ):
        # §3.4 — unknown variant must reject *before* any URL is opened.
        def fail_urlopen(*args, **kwargs):
            raise AssertionError("urlopen was called for an unknown variant")

        monkeypatch.setattr(
            "trailvideocut.plate.model_manager.urllib.request.urlopen",
            fail_urlopen,
        )
        with pytest.raises(ValueError):
            model_manager.download_model("bogus")

    def test_zero_arg_download_matches_m(self, isolated_cache, monkeypatch):
        """Zero-arg `download_model()` resolves to the default variant ("m")."""
        captured_urls: list[str] = []

        def fake_urlopen(url, timeout=0):
            captured_urls.append(url)
            return _FakeResponse([b"X"])

        monkeypatch.setattr(
            "trailvideocut.plate.model_manager.urllib.request.urlopen",
            fake_urlopen,
        )
        result = model_manager.download_model()
        assert result == isolated_cache / _EXPECTED_M_FILENAME
        assert captured_urls == [_EXPECTED_M_URL]

    def test_variants_isolated_on_disk(self, isolated_cache, monkeypatch):
        """Downloading s does not evict or alias n (and vice-versa)."""
        served = {
            _EXPECTED_N_URL: [b"N" * 8],
            _EXPECTED_S_URL: [b"S" * 16],
        }

        def fake_urlopen(url, timeout=0):
            chunks = served[url]
            return _FakeResponse(list(chunks))

        monkeypatch.setattr(
            "trailvideocut.plate.model_manager.urllib.request.urlopen",
            fake_urlopen,
        )
        n_path = model_manager.download_model("n")
        s_path = model_manager.download_model("s")
        assert n_path != s_path
        assert n_path.exists() and s_path.exists()
        assert n_path.read_bytes() == b"N" * 8
        assert s_path.read_bytes() == b"S" * 16
