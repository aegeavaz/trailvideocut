"""TrailVideoCut launcher for PyInstaller frozen builds.

Double-click: opens GUI (PySide6)
With arguments: runs CLI (typer)
"""

import os
import sys

if getattr(sys, "frozen", False):
    os.environ.setdefault(
        "IMAGEIO_FFMPEG_EXE", os.path.join(sys._MEIPASS, "ffmpeg.exe")
    )

if len(sys.argv) <= 1:
    from trailvideocut.ui.app import launch

    launch()
else:
    from trailvideocut.cli import app

    app()
