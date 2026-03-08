"""TrailVideoCut launcher for PyInstaller frozen builds.

Double-click: opens GUI (PySide6)
With arguments: runs CLI (typer)
"""

import os
import sys

if getattr(sys, "frozen", False):
    _meipass = sys._MEIPASS
    os.environ.setdefault(
        "IMAGEIO_FFMPEG_EXE", os.path.join(_meipass, "ffmpeg.exe")
    )
    # Add _MEIPASS to PATH so shutil.which() finds bundled ffmpeg/ffprobe.
    # This makes gpu._find_ffmpeg() and keyframes._find_ffprobe() work in
    # frozen builds without special-casing.
    _path = os.environ.get("PATH", "")
    if _meipass not in _path.split(os.pathsep):
        os.environ["PATH"] = _meipass + os.pathsep + _path

if len(sys.argv) <= 1:
    from trailvideocut.ui.app import launch

    launch()
else:
    from trailvideocut.cli import app

    app()
