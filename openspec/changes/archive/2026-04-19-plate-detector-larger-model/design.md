## Context

`PlateDetector` already accepts a `model_path` in its constructor (`src/trailvideocut/plate/detector.py:90-103`) — it does not hard-code a model internally. The hard-coding lives one layer above, in `plate/model_manager.py`, where `_MODEL_URL` and `_MODEL_FILENAME` are module-level constants. Every entry point (`review_page.py`, `workers.py`, `cli.py`) calls `get_model_path()` / `download_model()` with no arguments and receives the single YOLOv8n ONNX.

The UI has **no persistence layer** — no `QSettings`, no config file for user preferences. Detection parameters (confidence threshold, geometry filters) live on Review-page spin boxes and are read at detection-launch time. `TrailVideoCutConfig` exists but is populated by the setup wizard per-run and is not a user-preference store. The selected plate-model variant follows the same pattern as the existing spin boxes: a widget that is read when the user clicks "Detect Plates".

Downstream filters (vertical-split, phone-zone gate, geometry, tracker) are agnostic to which backbone produced the boxes — they consume `PlateBox` objects in normalized coordinates. A larger backbone therefore ripples no further than the ONNX file on disk.

## Goals / Non-Goals

**Goals:**
- Let a user pick `n`, `s`, or `m` at detection-launch time.
- Make adding a new variant a single dict-entry change.
- Ship the best-accuracy variant (`m`) as the default so the out-of-box experience exercises the full backbone improvement; users trade down to `s` / `n` when latency matters.
- Per-variant cache files so switching is cheap after the first download.

**Non-Goals:**
- No training or fine-tuning pipeline.
- No automated benchmark harness (manual side-by-side is sufficient for the first iteration).
- No changes to the generic COCO model used for phone detection.
- No changes to post-detection filters, tracker, blur, or export paths.
- No user-preference persistence (out of scope; the whole app lacks it).

## Decisions

### 1. Variant identifier is a single-letter string (`"n" | "s" | "m"`)

**Why**: Matches YOLO nomenclature (`yolov8n`, `yolov8s`, `yolov8m`) that users already see in documentation. Short enough for CLI flags and combo-box display. Extensible (`"l"`, `"x"`) without schema change.

**Alternative considered**: Enum (`ModelVariant.NANO`). Rejected — adds an import surface for a value that is already a meaningful short string at the UI/CLI boundary.

### 2. Registry lives in `model_manager.py` as a module-level dict

```python
_VARIANTS: dict[str, tuple[str, str]] = {
    # n: existing YOLOv8n (ml-debi). Unchanged URL + filename → zero regression.
    "n":  (_YOLOV8N_URL,  "plate_detector_yolov8n.onnx"),
    # s/m: YOLOv11 fine-tunes (morsetechlab, AGPL-3.0, ONNX pre-exported).
    "s":  (_YOLOV11S_URL, "plate_detector_yolov11s.onnx"),
    "m":  (_YOLOV11M_URL, "plate_detector_yolov11m.onnx"),
}
```

Variant keys `"s"` and `"m"` denote the *size* tier (small/medium) rather than the exact ultralytics family — the `n` entry is YOLOv8, the `s`/`m` entries are YOLOv11. This is pragmatic (`morsetechlab` publishes ONNX directly for v11 s/m; no equivalent v8 s/m is publicly pre-exported) and the detection post-processing in `PlateDetector._parse_output` is head-compatible across both families.

`get_model_path(variant: str = "m")` and `download_model(variant: str = "m", progress_callback=None)` resolve against this dict. Unknown variants raise `ValueError` with the list of supported keys.

**Why**: The existing module is already a thin path/URL resolver — extending it is the minimum-surface change. Default arg `"m"` makes zero-arg calls resolve to the largest / most-accurate variant.

**Alternative considered**: A `ModelRegistry` class with DI. Rejected as YAGNI for three static entries — reintroduce it only if the registry grows dynamic behaviour (e.g. loading from a JSON manifest).

### 3. `PlateDetector` constructor is unchanged

It already takes `model_path: str | Path`. Variant resolution is the caller's job. This preserves the current unit tests (912 lines in `tests/test_plate_detector.py`) and honours SRP: the detector runs inference; the manager resolves files.

**Alternative considered**: Push `variant` into `PlateDetector.__init__`. Rejected — couples the inference class to the resolver, forces every test fixture to understand variants, and leaks the registry into `detector.py`.

### 4. UI is a combo-box, no persistence

A `QComboBox` added next to the existing detection-parameter widgets in Review-page (`review_page.py:~218`). Items: `"YOLOv8n (fast)"`, `"YOLOv11s (medium, ~3× slower)"`, `"YOLOv11m (slow, ~8× slower, default)"` mapped to `"n" | "s" | "m"` via `itemData`. Default selection: `"m"` (index 2). Read at detection-launch.

**Why**: Consistent with how confidence / ratio / min-size are already handled (live widget → passed into worker). Users already expect "click detect to apply" semantics.

**Alternative considered**: Add persistence via `QSettings`. Rejected as scope creep — the rest of the UI lacks persistence, so doing it here would create a solo exception.

### 5. CLI flag + `TrailVideoCutConfig` stays untouched

`detect-plates` gains `--plate-model {n,s,m}` (default `m`) read locally in the CLI handler and forwarded to `download_model(variant)` / `get_model_path(variant)`. `TrailVideoCutConfig` is **not** modified — it's the render-pipeline config, not a detection-runtime config, and adding plate-model here would leak UI concerns into the pipeline dataclass.

**Alternative considered**: Put `plate_model_variant` on `TrailVideoCutConfig`. Rejected — that dataclass already has a drift problem between "CLI render config" and "UI state"; don't make it worse.

### 6. Downloads are lazy per variant

First use of a variant triggers a download (same pattern as today's n download). No pre-warming. The Review-page download dialog already exists (`review_page.py:952`) and is reusable — it just needs to know which filename to display.

### 7. Default-flip semantics

Zero-arg `get_model_path()` / `download_model()` now resolve to variant `"m"` (the largest variant). This is a deliberate behaviour change:

- First post-upgrade detection run triggers a one-time download of `plate_detector_yolov11m.onnx` (~100 MB).
- Per-frame inference is ~8× slower than the previous `n` default on CPU; GPU installs absorb most of the cost.
- The `n` ONNX already on disk from older installs is untouched — switching the combo back to `n` resumes the old behaviour with no re-download.

To offset the higher false-positive rate that `m` shows at low confidence, the default confidence threshold is raised from `0.05` to `0.20` (GUI spin, CLI `--threshold`, and `PlateDetector.__init__`).

## Risks / Trade-offs

- **[Risk] Source availability for s/m variants** — `ml-debi/yolov8-license-plate-detection` only ships n. Using a generic YOLOv8s COCO model won't detect plates as a class (there's no "license plate" in COCO). → **Mitigation**: before merging, confirm a public fine-tuned s/m plate ONNX (e.g. `keremberke/yolov8s-license-plate`, `keremberke/yolov8m-license-plate` which publish n/s/m for plates). If neither hosts an ONNX export, the `.pt` must be exported to ONNX once and checked in to a release asset or cache-shipped, because runtime `.pt`→ONNX conversion would reintroduce the `torch` hard dep. Tracked as an open question below.

- **[Risk] Detection quality regression with a different fine-tune** — a different uploader's s/m weights may have been trained on a different plate distribution (e.g. US vs EU plates) and perform **worse** than the current n on trail-specific footage. → **Mitigation**: the user can flip the combo back to `n` with no state to unwind. Document in the combo tooltip that larger is not always better.

- **[Risk] Latency regression on tiled-detection path** — tiled mode runs N crops per frame; multiplying per-crop cost by 8× (m) on a CPU-only install may make detection impractical. → **Mitigation**: tooltip warning on `m`. If a user reports unusable latency, we can later add a "disable tiling for m" heuristic — out of scope for this change.

- **[Risk] Cache directory bloat** — n ≈ 12 MB, s ≈ 45 MB, m ≈ 100 MB. All three held in cache ≈ 160 MB. → **Mitigation**: acceptable for a user cache. If it becomes a complaint, add a "clear unused variants" action later.

- **[Trade-off] Default-arg backward compat vs explicit signatures** — we use `variant="n"` defaults on `get_model_path` / `download_model` to stage the migration in small steps. Drawback: tests that monkey-patch these functions may miss the variant arg. → **Mitigation**: flip all call sites to pass the variant explicitly in the same PR; keep the default only as a safety net.

## Migration Plan

No data migration. Roll-forward only.

1. Introduce the registry and variant-aware functions in `model_manager.py`. The n entry uses the **existing** URL and filename — zero behaviour change for current users.
2. Migrate `workers.py`, `cli.py`, `review_page.py` call sites to pass `variant` (all defaulting to `"n"` initially so diffs are mechanical).
3. Add the combo-box + CLI flag wiring so the user-supplied variant flows through.
4. Confirm no Python-level or behavioural change when variant `"n"` is used.

**Rollback**: revert the change — the n ONNX file, URL, and cache filename are unchanged, so users' existing cache remains valid before and after.

## Open Questions

1. **Which concrete s/m plate-detection ONNX URLs do we register?** — **Resolved (2026-04-19).** Using `morsetechlab/yolov11-license-plate-detection`:
   - `s`: `https://huggingface.co/morsetechlab/yolov11-license-plate-detection/resolve/main/license-plate-finetune-v1s.onnx`
   - `m`: `https://huggingface.co/morsetechlab/yolov11-license-plate-detection/resolve/main/license-plate-finetune-v1m.onnx`

   Verified via the HF API `siblings` list that both `.onnx` files exist and are fetchable at the `resolve/main` URL. License on the host repo is **AGPL-3.0** (inherited from ultralytics). Weights are downloaded at runtime from HF and are never redistributed by this repo, so the existing `n`-variant download pattern (from `ml-debi/yolov8-license-plate-detection`, itself AGPL-derived) is unchanged — we are not creating a new license obligation for the binary.

   Rejected candidates: `keremberke/yolov8{s,m}-license-plate` (HF metadata unreachable / API inconsistency), `shalchianmh/Iran_license_plate_detection_YOLOv8m` (region-specific fine-tune likely to regress on trail footage), generic COCO YOLOv8 (no plate class). A self-hosted `.pt → .onnx` release asset was considered as a fallback but is unnecessary now that `morsetechlab` exports directly.

   Note: `morsetechlab` also publishes `v1n.onnx`. We intentionally do **not** swap the default `"n"` to it — the proposal promises zero regression for current users on the default variant, and that requires keeping the existing `ml-debi/yolov8-license-plate-detection` URL + cache filename. Users who want to try the v11 nano can simply pick `"s"` (smallest v11 variant registered).

2. **Should the combo default be remembered across app runs?** Current answer: no (matches rest of app). Revisit if users ask; it's a one-line `QSettings` addition at that point.

3. **Should `--plate-model` also be accepted by the `analyze` subcommand or any pipeline-level CLI?** Current answer: no, only `plate-detect`. Pipeline commands don't run plate detection standalone.
