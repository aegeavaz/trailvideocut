# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for TrailVideoCut Windows executable."""

import os
import imageio_ffmpeg
from PyInstaller.utils.hooks import copy_metadata

block_cipher = None

# Bundle imageio-ffmpeg's FFmpeg binary
ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
ffmpeg_data = [(ffmpeg_exe, ".")]

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=ffmpeg_data,
    datas=copy_metadata("imageio") + copy_metadata("imageio_ffmpeg"),
    hiddenimports=[
        "librosa",
        "soundfile",
        "scipy.signal",
        "sklearn.cluster",
        "sklearn.preprocessing",
        "opentimelineio",
        "moviepy.video.fx",
        "imageio_ffmpeg",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "cupy",
        "cupy_cuda12x",
        "tkinter",
        "matplotlib",
        "IPython",
        "notebook",
        "pytest",
        "ruff",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="TrailVideoCut",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
