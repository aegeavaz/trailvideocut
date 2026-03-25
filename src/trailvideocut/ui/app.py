import ctypes
import os
import sys

# Qt's FFmpeg backend may fail to auto-detect HW decoders; set priority list explicitly.
# Qt tries each in order, silently skips unavailable ones.
# d3d11va/d3d12va = Windows, cuda = NVIDIA Linux, vaapi = AMD/Intel Linux
os.environ.setdefault(
    "QT_FFMPEG_DECODING_HW_DEVICE_TYPES", "d3d11va,d3d12va,cuda,vaapi"
)

from PySide6.QtWidgets import QApplication

from trailvideocut.ui.main_window import MainWindow


def _d3d11_available() -> bool:
    """Probe whether the system can create a D3D11 hardware device.

    Returns False when D3D11 is unusable (missing/outdated drivers, old GPU,
    VM without GPU passthrough) so the caller can switch Qt to OpenGL before
    QApplication is created.
    """
    try:
        d3d11 = ctypes.WinDLL("d3d11", use_last_error=True)

        device = ctypes.c_void_p()
        feature_level = ctypes.c_uint()
        context = ctypes.c_void_p()

        D3D_DRIVER_TYPE_HARDWARE = 1
        D3D11_SDK_VERSION = 7

        hr = d3d11.D3D11CreateDevice(
            None,
            ctypes.c_uint(D3D_DRIVER_TYPE_HARDWARE),
            None,
            ctypes.c_uint(0),
            None,
            ctypes.c_uint(0),
            ctypes.c_uint(D3D11_SDK_VERSION),
            ctypes.byref(device),
            ctypes.byref(feature_level),
            ctypes.byref(context),
        )

        # Release COM objects (IUnknown::Release is vtable slot 2)
        for ptr in (context, device):
            if ptr.value:
                vt = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0]
                release = ctypes.cast(
                    ctypes.cast(vt, ctypes.POINTER(ctypes.c_void_p))[2],
                    ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p),
                )
                release(ptr)

        return hr >= 0
    except (OSError, Exception):
        return False


def launch():
    """Launch the TrailVideoCut graphical interface."""
    # On Windows, probe D3D11 before Qt tries it.  If the GPU cannot create a
    # D3D11 device, tell Qt to use OpenGL instead — avoids the
    # "D3D11 smoke test: Failed to create vertex shader" crash.
    if sys.platform == "win32" and not _d3d11_available():
        os.environ.setdefault("QSG_RHI_BACKEND", "opengl")

    app = QApplication(sys.argv)
    app.setApplicationName("TrailVideoCut")
    app.setOrganizationName("TrailVideoCut")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
