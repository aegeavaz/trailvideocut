# TrailVideoCut

Automatically cut motorcycle POV videos to sync with music beats.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Prosperity 3.0](https://img.shields.io/badge/license-Prosperity%203.0-green.svg)](LICENSE)

## Features

- **Beat-synced editing** — Detects beats, downbeats, and musical structure to time cuts precisely
- **Scene detection** — Finds natural scene boundaries using optical flow, color, and edge analysis
- **Energy-adaptive cuts** — Faster cuts during high-energy sections, longer clips during calm passages
- **GPU acceleration** — NVIDIA NVENC encoding, hardware decoding, CuPy-accelerated frame scoring
- **DaVinci Resolve export** — OTIO timeline export for manual refinement in DaVinci Resolve
- **Must-include marks** — Pin specific timestamps so they always appear in the final edit
- **CLI + GUI** — Full Typer CLI for scripting, PySide6 GUI for interactive workflow (Setup → Review → Export)

## Installation

### From PyPI

```bash
pip install trailvideocut

# With GUI support
pip install "trailvideocut[ui]"

# With NVIDIA GPU acceleration
pip install "trailvideocut[gpu]"
```

### From source

```bash
git clone https://github.com/aegeavaz/trailvideocut.git
cd trailvideocut
pip install -e ".[ui]"
```

### Windows executable

Download `TrailVideoCut.exe` from [GitHub Releases](https://github.com/aegeavaz/trailvideocut/releases). Double-click to open the GUI, or run from a terminal for CLI access.

## Usage

### CLI

```bash
# Basic beat-synced cut
trailvideocut cut ride.mp4 song.mp3 -o edit.mp4

# Export OTIO timeline for DaVinci Resolve
trailvideocut cut ride.mp4 song.mp3 --davinci

# Pin specific moments (in seconds)
trailvideocut cut ride.mp4 song.mp3 -i 42.5 -i 78.0

# Customize transitions and segment lengths
trailvideocut cut ride.mp4 song.mp3 -t crossfade --crossfade 0.3 --min-segment 1.5 --max-segment 6.0

# Disable GPU acceleration
trailvideocut cut ride.mp4 song.mp3 --no-gpu

# Analyze audio or video independently
trailvideocut analyze --audio song.mp3
trailvideocut analyze --video ride.mp4

# Launch the GUI
trailvideocut ui
```

### GUI

1. **Setup** — Load video and audio files, configure transition style and parameters
2. **Review** — Preview detected beats, adjust must-include marks, tweak segment boundaries
3. **Export** — Render the final video or export an OTIO timeline for DaVinci Resolve

## How it works

TrailVideoCut runs a 5-phase pipeline:

1. **Audio analysis** — Extracts beats, downbeats, tempo, and musical structure (intro, verse, chorus, etc.) using librosa
2. **Video analysis** — Scores every segment of footage by optical flow, color variance, edge density, and brightness change
3. **Beat mapping** — Maps musical beats to cut points, adapting cut frequency to section energy
4. **Clip selection** — Assigns the highest-scoring video segments to each beat interval, respecting must-include marks and quality thresholds
5. **Rendering** — Assembles the final video with crossfades using FFmpeg (GPU-accelerated when available), or exports an OTIO timeline

## Disclaimer

### Music and footage rights

**You are solely responsible for ensuring you have the necessary rights to any music and video footage used with this software.** Using copyrighted music without proper authorization (license, permission, or applicable exception) may violate copyright laws in your jurisdiction.

### Video footage

Ensure your footage does not contain content requiring additional licensing, including identifiable persons (right of publicity/privacy), trademarks, or third-party audio tracks embedded in the video.

### No warranty

This software is provided "as is", without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose, and non-infringement. In no event shall the authors be liable for any claim, damages, or other liability arising from the use of this software.

### Third-party software

TrailVideoCut depends on third-party libraries and tools, each under their own licenses:

- [FFmpeg](https://ffmpeg.org/) — LGPL / GPL
- [librosa](https://librosa.org/) — ISC
- [OpenCV](https://opencv.org/) — Apache 2.0
- [MoviePy](https://zulko.github.io/moviepy/) — MIT
- [PySide6](https://www.qt.io/) — LGPL
- [OpenTimelineIO](https://opentimeline.io/) — Apache 2.0

## License

This project is licensed under the [Prosperity Public License 3.0.0](LICENSE) — free for non-commercial use. For commercial licensing, contact the author.
