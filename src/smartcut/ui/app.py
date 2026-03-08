import os
import sys

# Qt's FFmpeg backend may fail to auto-detect HW decoders; set priority list explicitly.
# Qt tries each in order, silently skips unavailable ones.
# d3d11va/d3d12va = Windows, cuda = NVIDIA Linux, vaapi = AMD/Intel Linux
os.environ.setdefault(
    "QT_FFMPEG_DECODING_HW_DEVICE_TYPES", "d3d11va,d3d12va,cuda,vaapi"
)

from PySide6.QtWidgets import QApplication

from smartcut.ui.main_window import MainWindow


def launch():
    """Launch the SmartCut graphical interface."""
    app = QApplication(sys.argv)
    app.setApplicationName("SmartCut")
    app.setOrganizationName("SmartCut")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
