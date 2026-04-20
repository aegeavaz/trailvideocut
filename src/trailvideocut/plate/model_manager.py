"""Download and cache the plate detection ONNX model."""

import sys
from pathlib import Path
import urllib.request

# Plate-detection model variant registry.
#
# Each entry maps a user-facing size tier to a `(download URL, cache filename)`
# pair. Adding a new variant is a one-entry change. The `"n"` entry preserves
# the pre-change URL and cache filename so that existing users see no
# regression and no re-download on upgrade.
#
# Variants:
#   "n": YOLOv8n fine-tune from `ml-debi/yolov8-license-plate-detection`
#        (ONNX export, MIT claim on the host card).
#   "s": YOLOv11s fine-tune from `morsetechlab/yolov11-license-plate-detection`
#        (AGPL-3.0 on the host repo, inherited from ultralytics). The ONNX is
#        downloaded at runtime from HF and is never redistributed with this
#        repo, matching the existing `"n"` fetch pattern.
#   "m": YOLOv11m fine-tune from the same host / license as `"s"`.
#
# Note: `"s"` and `"m"` are a different ultralytics family (v11) than `"n"`
# (v8). The detection head is format-compatible across both families, and the
# post-detection filter stack in `PlateDetector` is unchanged.
_VARIANTS: dict[str, tuple[str, str]] = {
    "n": (
        "https://huggingface.co/ml-debi/yolov8-license-plate-detection"
        "/resolve/main/best.onnx",
        "plate_detector_yolov8n.onnx",
    ),
    "s": (
        "https://huggingface.co/morsetechlab/yolov11-license-plate-detection"
        "/resolve/main/license-plate-finetune-v1s.onnx",
        "plate_detector_yolov11s.onnx",
    ),
    "m": (
        "https://huggingface.co/morsetechlab/yolov11-license-plate-detection"
        "/resolve/main/license-plate-finetune-v1m.onnx",
        "plate_detector_yolov11m.onnx",
    ),
}

# Generic YOLOv8n COCO model bundled in the repo for ONNX-backed phone
# detection. Shipped under `resources/yolov8n.onnx` so onnxruntime-only
# installs (e.g. Windows DirectML) can run phone filtering without
# requiring the `ultralytics` + `torch` dependency.
_COCO_MODEL_FILENAME = "yolov8n.onnx"


def _resolve_variant(variant: str) -> tuple[str, str]:
    """Return (url, cache_filename) for a variant, or raise ValueError."""
    try:
        return _VARIANTS[variant]
    except KeyError:
        supported = sorted(_VARIANTS.keys())
        raise ValueError(
            f"Unknown plate-model variant {variant!r}. "
            f"Supported variants: {supported}."
        ) from None


def get_cache_dir() -> Path:
    """Return platform-appropriate cache directory for model files."""
    cache = Path.home() / ".cache" / "trailvideocut"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def get_model_path(variant: str = "m") -> Path | None:
    """Return path to the cached model file for ``variant``, or ``None``.

    Args:
        variant: One of ``"n"``, ``"s"``, ``"m"``. Defaults to ``"m"`` —
            the largest variant, preferred for recall and box tightness on
            small/distant plates. Unknown variants raise ``ValueError``.
    """
    _, filename = _resolve_variant(variant)
    path = get_cache_dir() / filename
    return path if path.exists() else None


def get_coco_model_path() -> Path | None:
    """Return the path to the bundled generic YOLOv8n COCO ONNX model.

    The model ships with the repository under ``resources/yolov8n.onnx`` so
    it is available on every install without a network fetch. Under
    PyInstaller the bundled file lives next to ``sys._MEIPASS``. Returns
    ``None`` if the file is missing.
    """
    # Frozen (PyInstaller) builds unpack datas to sys._MEIPASS.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "resources" / _COCO_MODEL_FILENAME
        if candidate.exists():
            return candidate
    # Dev path: src/trailvideocut/plate/ -> src/trailvideocut/ -> src/ -> repo_root/
    repo_root = Path(__file__).resolve().parents[3]
    path = repo_root / "resources" / _COCO_MODEL_FILENAME
    return path if path.exists() else None


def download_model(variant: str = "m", progress_callback=None) -> Path:
    """Download the ONNX model for ``variant`` to the cache directory.

    Args:
        variant: One of ``"n"``, ``"s"``, ``"m"``. Defaults to ``"m"`` —
            the largest / most-accurate variant. Unknown variants raise
            ``ValueError`` before any network call.
        progress_callback: Optional callable(bytes_downloaded, total_bytes).

    Returns:
        Path to the cached ONNX file for the requested variant. Skips the
        download and returns the existing path if the cache already holds it.
    """
    url, filename = _resolve_variant(variant)
    path = get_cache_dir() / filename
    if path.exists():
        return path

    tmp = path.with_suffix(".tmp")
    try:
        req = urllib.request.urlopen(url, timeout=60)  # noqa: S310
        total = int(req.headers.get("Content-Length", 0))
        downloaded = 0
        with open(tmp, "wb") as f:
            while True:
                chunk = req.read(8192)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback(downloaded, total)
        tmp.rename(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return path
