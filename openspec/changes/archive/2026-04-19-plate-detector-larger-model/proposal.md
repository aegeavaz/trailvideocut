## Why

The current plate detector runs a fine-tuned **YOLOv8n** (nano) ONNX model hard-coded in `model_manager.py`. Users report two concrete failure modes that the downstream filter stack (upper-half gate, phone-zone filter, blur tightening) cannot fix after the fact:

1. **Missed plates** — small/distant/off-angle plates are never emitted by the detector, so no post-filter can recover them.
2. **Loose boxes** — boxes that bleed around the plate edges, causing the blur to over- or under-cover.

Both symptoms are characteristic of an under-parametrized backbone. Before investing in training or architectural work, we want to **empirically test whether a larger pre-trained plate-detection backbone (YOLOv11s or YOLOv11m) improves recall and box tightness** on real trail footage — with an easy rollback if it regresses latency or false-positive rate. (The default `n` stays on the existing YOLOv8n weights for zero-regression; `s`/`m` are sourced from `morsetechlab/yolov11-license-plate-detection` which publishes pre-exported ONNX directly — see `design.md` → Open Questions for the sourcing decision.)

## What Changes

- Make the plate-detection model source **selectable at runtime** (current hard-coded n → choice of n / s / m), and flip the default to `m` (YOLOv11m) for best-effort recall / box tightness out of the box. Users who find `m` too slow drop to `s` or `n` via the combo-box / CLI flag.
- Extend `model_manager` with a **model-variant registry** (URL + cached filename per variant) and variant-aware `get_model_path(variant)` / `download_model(variant, …)` functions.
- Add a **"Plate Model" combo-box** to the Review-page detection controls (alongside the existing confidence / geometry spin boxes). The selected variant is read directly at detection-launch time and passed through to `PlateDetector` — no new persistence layer (the rest of the detection controls already work this way). Default selection: `m`.
- Add a CLI flag `--plate-model {n,s,m}` to the `detect-plates` CLI entry for headless A/B runs. Default: `m`.
- Raise the default detection confidence threshold from `0.05` to `0.20` (GUI spin, CLI `--threshold`, and `PlateDetector.__init__`) to offset the false-positive rate increase that the larger default backbone brings at low confidence.
- Propagate the selected variant through the worker/CLI paths that currently call `download_model()` / `get_model_path()` so the active variant is the one downloaded/loaded.
- Cache each variant under its own filename so switching between variants doesn't force a re-download of the previously-used one.
- Keep all downstream filters (vertical-split, phone-zone gate, geometry) and the `PlateDetector.__init__` inference pipeline **unchanged** — this change is strictly about which ONNX file is loaded.

Not in scope (explicit non-goals):
- No training or fine-tuning pipeline.
- No automatic benchmarking harness (manual side-by-side is enough for the first iteration).
- No change to the generic COCO model used for phone detection.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `plate-detector`: the "Model loading and caching" requirement is extended from a single hard-coded ONNX to a set of supported variants selected at construction time; a new requirement formalizes the variant-selection contract and per-variant caching.

## Impact

- **Code**:
  - `src/trailvideocut/plate/model_manager.py` — variant registry (dict of `{variant → (url, cache_filename)}`), variant-aware `get_model_path(variant)` and `download_model(variant, progress_callback)`. Existing zero-arg signatures kept as thin wrappers that default to `"n"` for backward compatibility.
  - `src/trailvideocut/ui/review_page.py` (near line 218 where the other detection widgets are built; call sites at 902/916/1557/1563) — new combo-box, passed through to the worker/detector construction at detection-launch time.
  - `src/trailvideocut/ui/workers.py` (line 264) — accept `variant` argument and forward to `download_model(variant, …)`.
  - `src/trailvideocut/cli.py` (line 277) — new `--plate-model {n,s,m}` argparse flag (default `n`), forwarded to `download_model` / `get_model_path` and to `PlateDetector`.
  - `src/trailvideocut/plate/detector.py` — **no change**. It already accepts `model_path` at construction; variant selection happens upstream.
- **Dependencies**: no new packages. The existing ultralytics / onnxruntime / cv2.dnn backends already handle s/m variants natively.
- **On-disk cache**: each variant cached under its own filename in `~/.cache/trailvideocut/` — n remains at `plate_detector_yolov8n.onnx`; s/m cache as `plate_detector_yolov11s.onnx` / `plate_detector_yolov11m.onnx`. First post-upgrade detection run triggers a one-time ~100 MB download of the `m` variant (new default).
- **Performance**: s ≈ 3× and m ≈ 8× slower than n per frame — surfaced as a combo-box tooltip. Tiled-detection throughput is the worst-affected path.
- **Tests**: `tests/test_model_manager.py` (new) — variant registry resolution and per-variant path isolation. `tests/test_plate_detector.py` — no changes needed (already parameterized on `model_path`).
- **Risk**: larger default variant has a higher false-positive rate at low confidence → mitigated by raising the default confidence to `0.20`. Users who find `m` too slow flip the combo to `s` or `n` and relaunch. No persistent state to unwind.
- **Open model sourcing**: resolved — s/m variants use the ONNX exports published by `morsetechlab/yolov11-license-plate-detection` (AGPL-3.0, downloaded at runtime from HF, not redistributed by this repo). See `design.md` → Open Questions for the full rationale. The registry is shaped so adding a variant remains a one-line change.
