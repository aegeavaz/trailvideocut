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
- **Must-include marks** — Pin specific timestamps so they always appear in the final edit; auto-saved as a `{video_stem}.marks.json` sidecar and reloaded when you reopen the video
- **Exclusion ranges** — Skip boring time spans (mount-up, stops, dead air) so the selector never picks from them
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

# Skip time ranges from clip selection (repeatable, START:END in seconds)
# The selector never picks clips whose midpoint falls inside an excluded
# range. Ranges are auto-saved as a `{video_stem}.exclusions.json` sidecar
# when edited in the GUI; the CLI flag takes precedence for that invocation.
trailvideocut cut ride.mp4 song.mp3 -x 0:30 -x 120:135

# Customize transitions and segment lengths
trailvideocut cut ride.mp4 song.mp3 -t crossfade --crossfade 0.3 --min-segment 1.5 --max-segment 6.0

# Disable GPU acceleration
trailvideocut cut ride.mp4 song.mp3 --no-gpu

# Analyze audio or video independently
trailvideocut analyze --audio song.mp3
trailvideocut analyze --video ride.mp4

# Run plate detection with the default (YOLOv11m) model
trailvideocut detect-plates ride.mp4 -o plate_debug

# Drop to a smaller/faster backbone when per-frame latency matters
# (s ≈ 3× faster than m; n ≈ 8× faster than m but with lower recall)
trailvideocut detect-plates ride.mp4 --plate-model s
trailvideocut detect-plates ride.mp4 --plate-model n

# Launch the GUI
trailvideocut ui
```

**Plate detection model (`--plate-model {n,s,m}`)** — selects which ONNX
backbone runs plate detection. Default `m` is YOLOv11m (best recall and
box tightness on small or distant plates, ~8× slower than `n`). `s`
(YOLOv11s, ~3× slower than `n`) is the middle ground, and `n` is the
existing YOLOv8n (fastest). `s` and `m` are fine-tuned plate detectors
published by `morsetechlab/yolov11-license-plate-detection`; larger
variants may regress the false-positive rate at low confidence
thresholds, so the GUI default confidence was raised to 20% to compensate.
Each variant is cached under its own filename, so switching between them
never forces a re-download after the first use. The Review-page GUI
exposes the same choice via a "Plate Model" combo-box next to the other
detection controls.

### GUI

1. **Setup** — Load video and audio files, configure transition style and parameters. Use the **Excluded** sub-tab to mark time ranges the clip selector should skip — Start/End buttons (keyboard `I`/`O`) capture the current player position; ranges auto-save to a sidecar and show as shaded red spans on the scrubber.
2. **Review** — Preview detected beats, adjust must-include marks, tweak segment boundaries
3. **Export** — Render the final video or export an OTIO timeline for DaVinci Resolve

#### Keyboard shortcuts

Setup page — shortcuts fire while the page is focused:

| Key         | Action                                                |
| ----------- | ----------------------------------------------------- |
| `Space`     | Play / pause                                          |
| `← / →`     | Step one frame back / forward (hold for auto-repeat)  |
| `↑ / ↓`     | Jump forward / back                                   |
| `Home / End`| Go to the start / end of the video                    |
| `A`         | Add a must-include mark at the current frame          |
| `D`         | Remove the selected mark (or the mark nearest the current frame) |
| `I / O`     | Capture an exclusion range **I**n / **O**ut point     |
| `Esc`       | Cancel a pending exclusion range                      |

#### Marks

Must-include marks are timestamps the clip selector always preserves in the final edit — use `A` while scrubbing to pin a beat-aligned moment. Marks auto-save to `{video_stem}.marks.json` next to the video as you add, remove, or clear them, so there is no Save button — reopening the same video restores every mark. To reuse a mark set from a different video, copy its sidecar and rename it to match the new video's stem (e.g. `old.marks.json` → `new.marks.json`).

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
