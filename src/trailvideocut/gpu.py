"""GPU detection and capability reporting for TrailVideoCut."""

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
    hwaccel_available: bool = False
    hwaccels: tuple[str, ...] = ()
    gpu_name: str = ""
    gpu_memory_mb: int = 0
    system_ffmpeg: str = ""

    @property
    def any_gpu(self) -> bool:
        return self.cupy_available or self.nvenc_available or self.nvdec_available or self.hwaccel_available


def _find_ffmpeg() -> str | None:
    """Find an ffmpeg binary: system PATH first, then imageio-ffmpeg fallback.

    The imageio-ffmpeg binary bundled with moviepy is a static build that
    typically lacks hardware *encoders* (NVENC), but may still support
    hardware *decoding* via platform APIs (D3D11VA, VideoToolbox, VAAPI)
    through ``-hwaccel auto``.
    """
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg

        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path:
            return path
    except Exception:
        pass
    return None


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


def _check_ffmpeg_hwaccels(ffmpeg_bin: str) -> tuple[str, ...]:
    """Query ``ffmpeg -hwaccels`` and return available hardware acceleration methods.

    Returns a tuple of method names (e.g. ``("cuda", "d3d11va", "dxva2")``).
    """
    try:
        result = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-hwaccels"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return ()
        # Output format: first line is "Hardware acceleration methods:", then one per line
        lines = result.stdout.strip().splitlines()
        methods: list[str] = []
        for line in lines[1:]:  # skip header
            method = line.strip()
            if method:
                methods.append(method)
        return tuple(methods)
    except (subprocess.TimeoutExpired, OSError):
        return ()


@functools.lru_cache(maxsize=1)
def detect_gpu() -> GPUCapabilities:
    """Detect GPU capabilities: CuPy for compute, HW accel for decoding/encoding.

    Checks the system ffmpeg first, falling back to the imageio-ffmpeg
    bundled binary.  The bundled binary typically lacks hardware *encoders*
    (NVENC) but may still support platform-native HW *decoding* via
    ``-hwaccel auto`` (D3D11VA, VideoToolbox, VAAPI, etc.).

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

    # 3. Check ffmpeg for hardware codec support (NVENC/NVDEC/hwaccels).
    #    Prefer the system binary (which usually has full HW codec support),
    #    but fall back to imageio-ffmpeg's bundled binary which may still
    #    support platform-native HW decoding (D3D11VA, VideoToolbox, VAAPI).
    nvdec_available = False
    hwaccels: tuple[str, ...] = ()
    ffmpeg_bin = _find_ffmpeg()
    if ffmpeg_bin:
        system_ffmpeg = ffmpeg_bin
        if _check_ffmpeg_nvenc(ffmpeg_bin):
            nvenc_available = True
        if _check_ffmpeg_nvdec(ffmpeg_bin):
            nvdec_available = True
        hwaccels = _check_ffmpeg_hwaccels(ffmpeg_bin)

    caps = GPUCapabilities(
        cupy_available=cupy_available,
        nvenc_available=nvenc_available,
        nvdec_available=nvdec_available,
        hwaccel_available=len(hwaccels) > 0,
        hwaccels=hwaccels,
        gpu_name=gpu_name,
        gpu_memory_mb=gpu_memory_mb,
        system_ffmpeg=system_ffmpeg,
    )

    if caps.any_gpu:
        logger.info("GPU detected: %s (%d MB)", gpu_name, gpu_memory_mb)
        logger.info(
            "  CuPy: %s, NVENC: %s, NVDEC: %s, HW accels: %s",
            cupy_available, nvenc_available, nvdec_available,
            ", ".join(hwaccels) if hwaccels else "none",
        )
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
