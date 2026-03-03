"""GPU detection and capability reporting for SmartCut."""

from __future__ import annotations

import functools
import logging
import shutil
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GPUCapabilities:
    """Detected GPU capabilities."""

    cupy_available: bool = False
    nvenc_available: bool = False
    nvdec_available: bool = False
    gpu_name: str = ""
    gpu_memory_mb: int = 0
    system_ffmpeg: str = ""

    @property
    def any_gpu(self) -> bool:
        return self.cupy_available or self.nvenc_available or self.nvdec_available


def _check_ffmpeg_nvenc(ffmpeg_bin: str) -> bool:
    """Check whether a specific ffmpeg binary supports h264_nvenc."""
    try:
        result = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0 and "h264_nvenc" in result.stdout
    except (subprocess.TimeoutExpired, OSError):
        return False


def _check_ffmpeg_nvdec(ffmpeg_bin: str) -> bool:
    """Check whether a specific ffmpeg binary supports h264_cuvid (NVDEC)."""
    try:
        result = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-decoders"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0 and "h264_cuvid" in result.stdout
    except (subprocess.TimeoutExpired, OSError):
        return False


@functools.lru_cache(maxsize=1)
def detect_gpu() -> GPUCapabilities:
    """Detect GPU capabilities: CuPy for compute, NVENC for encoding.

    NVENC detection checks the system ffmpeg (not moviepy's bundled one),
    since the bundled imageio-ffmpeg binary typically lacks hardware encoders.
    When NVENC is available, ``configure_moviepy_ffmpeg()`` should be called
    to point moviepy at the system binary.

    Results are cached — safe to call multiple times.
    """
    gpu_name = ""
    gpu_memory_mb = 0
    cupy_available = False
    nvenc_available = False
    system_ffmpeg = ""

    # 1. Probe nvidia-smi for GPU info
    if shutil.which("nvidia-smi"):
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                line = result.stdout.strip().split("\n")[0]
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2:
                    gpu_name = parts[0]
                    try:
                        gpu_memory_mb = int(float(parts[1]))
                    except ValueError:
                        pass
        except (subprocess.TimeoutExpired, OSError):
            pass

    # 2. Check CuPy availability
    try:
        import cupy as cp  # noqa: F401

        # Verify GPU is actually accessible
        cp.array([1.0])
        cupy_available = True
    except Exception:
        cupy_available = False

    # 3. Check system ffmpeg for hardware codec support (NVENC/NVDEC).
    #    moviepy bundles imageio-ffmpeg which is a static build without
    #    hardware codecs, so we must check the system binary instead.
    nvdec_available = False
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        system_ffmpeg = ffmpeg_bin
        if _check_ffmpeg_nvenc(ffmpeg_bin):
            nvenc_available = True
        if _check_ffmpeg_nvdec(ffmpeg_bin):
            nvdec_available = True

    caps = GPUCapabilities(
        cupy_available=cupy_available,
        nvenc_available=nvenc_available,
        nvdec_available=nvdec_available,
        gpu_name=gpu_name,
        gpu_memory_mb=gpu_memory_mb,
        system_ffmpeg=system_ffmpeg,
    )

    if caps.any_gpu:
        logger.info("GPU detected: %s (%d MB)", gpu_name, gpu_memory_mb)
        logger.info("  CuPy: %s, NVENC: %s, NVDEC: %s", cupy_available, nvenc_available, nvdec_available)
    else:
        logger.info("No GPU acceleration available — using CPU")

    return caps


def configure_moviepy_ffmpeg() -> None:
    """Point moviepy at the system ffmpeg when NVENC is available.

    The bundled imageio-ffmpeg binary lacks hardware encoders.
    Call this before any moviepy write operation that uses NVENC.

    moviepy's writer and reader modules do ``from moviepy.config import
    FFMPEG_BINARY`` at import time, creating local copies that are not
    affected by patching ``moviepy.config`` alone.  We patch all three
    module-level bindings so the system binary is used everywhere.
    """
    caps = detect_gpu()
    if caps.nvenc_available and caps.system_ffmpeg:
        import moviepy.config as mpy_config
        import moviepy.video.io.ffmpeg_writer as mpy_writer
        import moviepy.video.io.ffmpeg_reader as mpy_reader

        mpy_config.FFMPEG_BINARY = caps.system_ffmpeg
        mpy_writer.FFMPEG_BINARY = caps.system_ffmpeg
        mpy_reader.FFMPEG_BINARY = caps.system_ffmpeg
        logger.info("Switched moviepy to system ffmpeg: %s", caps.system_ffmpeg)


def patch_nvenc_pixel_format() -> None:
    """Fix moviepy hardcoding ``yuva420p`` for NVENC.

    moviepy's ``FFMPEG_VideoWriter.__init__`` appends
    ``-pix_fmt yuva420p`` after our ``ffmpeg_params`` for h264_nvenc.
    NVENC does not support ``yuva420p``, and the last ``-pix_fmt`` wins
    in ffmpeg, so our ``yuv420p`` gets silently overridden.

    This wraps the writer's ``__init__`` to replace ``yuva420p`` with
    ``yuv420p`` in the ffmpeg command before the subprocess starts.
    """
    import subprocess
    import moviepy.video.io.ffmpeg_writer as mpy_writer

    original_init = mpy_writer.FFMPEG_VideoWriter.__init__

    # Guard against double-patching
    if getattr(original_init, "_nvenc_patched", False):
        return

    @functools.wraps(original_init)
    def _patched_init(self, *args, **kwargs):
        _orig_popen = subprocess.Popen

        def _fix_yuva(cmd, **kw):
            if isinstance(cmd, list):
                cmd = [("yuv420p" if c == "yuva420p" else c) for c in cmd]
            return _orig_popen(cmd, **kw)

        subprocess.Popen = _fix_yuva
        try:
            original_init(self, *args, **kwargs)
        finally:
            subprocess.Popen = _orig_popen

    _patched_init._nvenc_patched = True
    mpy_writer.FFMPEG_VideoWriter.__init__ = _patched_init
    logger.info("Patched moviepy FFMPEG_VideoWriter for NVENC yuv420p")


def get_encoder_codec(force_cpu: bool = False) -> str:
    """Return the best available video encoder codec.

    Returns 'h264_nvenc' when GPU is available and not forced to CPU,
    otherwise 'libx264'.
    """
    if force_cpu:
        return "libx264"
    caps = detect_gpu()
    return "h264_nvenc" if caps.nvenc_available else "libx264"
