"""Download and cache the plate detection ONNX model."""

import sys
from pathlib import Path
import urllib.request

# YOLOv8n license plate detection model (ONNX format, MIT license)
# Source: https://huggingface.co/ml-debi/yolov8-license-plate-detection
_MODEL_URL = (
    "https://huggingface.co/ml-debi/yolov8-license-plate-detection"
    "/resolve/main/best.onnx"
)
_MODEL_FILENAME = "plate_detector_yolov8n.onnx"

# Generic YOLOv8n COCO model bundled in the repo for ONNX-backed phone
# detection. Shipped under `resources/yolov8n.onnx` so onnxruntime-only
# installs (e.g. Windows DirectML) can run phone filtering without
# requiring the `ultralytics` + `torch` dependency.
_COCO_MODEL_FILENAME = "yolov8n.onnx"


def get_cache_dir() -> Path:
    """Return platform-appropriate cache directory for model files."""
    cache = Path.home() / ".cache" / "trailvideocut"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def get_model_path() -> Path | None:
    """Return path to the cached model file, or None if not yet downloaded."""
    path = get_cache_dir() / _MODEL_FILENAME
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


def download_model(progress_callback=None) -> Path:
    """Download the model file to the cache directory.

    Args:
        progress_callback: Optional callable(bytes_downloaded, total_bytes).
    Returns:
        Path to the downloaded model file.
    """
    path = get_cache_dir() / _MODEL_FILENAME
    if path.exists():
        return path

    tmp = path.with_suffix(".tmp")
    try:
        req = urllib.request.urlopen(_MODEL_URL, timeout=60)  # noqa: S310
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
