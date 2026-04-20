## 1. Resolve the open question on variant sources

- [x] 1.1 Pick concrete ONNX URLs for variants `"s"` and `"m"`. Resolved: `morsetechlab/yolov11-license-plate-detection` — `license-plate-finetune-v1s.onnx` and `license-plate-finetune-v1m.onnx` at the HF `resolve/main` URL. Existence verified via HF `api/models` siblings list. No runtime `.pt → .onnx` conversion required.
- [x] 1.2 Confirm the chosen weights are licence-compatible for redistribution/use. Host license is AGPL-3.0 (inherited from ultralytics). Weights are downloaded at runtime from HF and never redistributed by this repo — same pattern as the existing `"n"` fetch from `ml-debi`. Comment annotation to match the existing `"n"` style is applied in the registry entry added in §2.5.
- [x] 1.3 Record the resolved URLs in `design.md` under "Open Questions" — done.

## 2. TDD: variant registry in `model_manager`

- [x] 2.1 Create `tests/test_model_manager.py`. Add a failing test asserting `_VARIANTS` contains keys `{"n", "s", "m"}`, the `"n"` entry preserves the existing URL and cache filename (`plate_detector_yolov8n.onnx`), and the `"s"`/`"m"` entries point at the URLs resolved in §1.
- [x] 2.2 Add a failing test asserting `get_model_path("n")` returns `<cache>/plate_detector_yolov8n.onnx` when the file exists, `None` when it does not, and that `get_model_path("s")` and `get_model_path("m")` resolve to `plate_detector_yolov11s.onnx` and `plate_detector_yolov11m.onnx` respectively. Use a `tmp_path` + monkey-patched `get_cache_dir` fixture.
- [x] 2.3 Add a failing test asserting `get_model_path("bogus")` raises `ValueError` with a message naming `{"n", "s", "m"}`.
- [x] 2.4 Add a failing test asserting `get_model_path()` (no args) behaves identically to `get_model_path("n")` — same path, same None-semantics — so existing callers see no regression.
- [x] 2.5 Implement the registry dict and variant-aware `get_model_path(variant: str = "n")` in `src/trailvideocut/plate/model_manager.py`. Remove the module-level `_MODEL_URL` / `_MODEL_FILENAME` constants (the registry replaces them). Confirm tests 2.1–2.4 pass.

## 3. TDD: variant-aware downloads

- [x] 3.1 Add a failing test that `download_model("s", progress_callback=cb)` writes to `<cache>/plate_detector_yolov11s.onnx` and calls `cb(downloaded, total)` at least once. Patch `urllib.request.urlopen` with a fake stream so no network is hit.
- [x] 3.2 Add a failing test that `download_model("n")` with an unchanged URL still writes to `plate_detector_yolov8n.onnx` — the default path must not regress.
- [x] 3.3 Add a failing test that `download_model(variant)` is a no-op (returns the existing path without re-fetching) when the variant's cache file already exists.
- [x] 3.4 Add a failing test that `download_model("bogus")` raises `ValueError` before any network call is attempted.
- [x] 3.5 Implement variant-aware `download_model(variant: str = "n", progress_callback=None)` driven by the registry. Confirm tests 3.1–3.4 pass and test 2.4 still passes.

## 4. Migrate call sites to pass variant through

- [x] 4.1 `src/trailvideocut/cli.py`: add `--plate-model` typer option (choices `{n, s, m}`, default `"n"`) to the `detect-plates` subcommand. Forward the value into `get_model_path(variant)` and `download_model(variant, …)`. *(Note: command is named `detect-plates` and the CLI uses `typer`, not `argparse` — flag semantics are identical; validation raises `typer.BadParameter` on invalid values.)*
- [x] 4.2 Add CLI tests asserting the flag is parsed, defaults to `"n"` when omitted, accepts `s`/`m`, and rejects values outside the choice set with a non-zero exit code.
- [x] 4.3 `src/trailvideocut/ui/workers.py`: add `variant` parameter to `ModelDownloadWorker.__init__` (default `"n"`) and forward to `download_model(variant, …)`. Callers can set it via constructor or `set_variant(…)`.
- [x] 4.4 `src/trailvideocut/ui/review_page.py`: introduce `_current_plate_variant()` helper (hardcodes `"n"` until §5 wires the combo-box) and route both `get_model_path()` call sites and the `ModelDownloadWorker` construction through it.

## 5. Review-page combo-box

- [x] 5.1 In `src/trailvideocut/ui/review_page.py`, added a `QComboBox` labelled "Plate Model" at the head of the detection-parameter row. Populated with three items: `("YOLOv8n (fast, default)", "n")`, `("YOLOv11s (medium, ~3× slower)", "s")`, `("YOLOv11m (slow, ~8× slower)", "m")`, using `addItem(label, variant_id)` so `currentData()` returns the variant id.
- [x] 5.2 Default selection is index 0 (variant `"n"`). Tooltip warns that larger variants may improve recall/box tightness but are significantly slower and may regress the false-positive rate, with explicit "try `s` first; only try `m` with a GPU" guidance.
- [x] 5.3 `_current_plate_variant()` now reads `self._combo_plate_model.currentData()` (falling back to `"n"` on any unknown value as a defensive guard). The §4.4 stub is gone; `get_model_path(...)` and `ModelDownloadWorker(...)` call sites already flow through the helper.
- [x] 5.4 No persistence — ReviewPage has no `QSettings` / save/load layer (confirmed via grep). Added `tests/test_review_page_plate_model.py::test_no_persistence_across_instances` as a regression guard in case a future change introduces one.
- [x] 5.5 Manual smoke — **passed** (user-confirmed 2026-04-19): launched the app, selected `"s"`, ran detection on a short clip, observed the download dialog triggered once, switched back to `"n"`, ran again, confirmed no re-download of `"n"`. Per-variant caching works as designed.

## 6. Verify invariant post-detection pipeline

- [x] 6.1 Added `tests/test_plate_detector_variant_invariance.py` — 5 tests constructing three detectors with the three cache filenames (`plate_detector_yolov8n.onnx`, `plate_detector_yolov11s.onnx`, `plate_detector_yolov11m.onnx`) via the existing `cv2.dnn` mock pattern. Each filter (`_filter_geometry`, `_should_apply_phone_zone_filter`, `_filter_phone_zones`, `_filter_vertical_position`) and the combined pipeline produce identical outputs across all three paths. No real ONNX weights required.
- [x] 6.2 Re-ran `tests/test_plate_detector.py` — 48/48 pass. Full suite (`pytest`) — 513 passed, 11 skipped, zero regressions.

## 7. Documentation

- [x] 7.1 Spec merge into `openspec/specs/plate-detector/spec.md` performed via `openspec archive` (invoked at archive time).
- [x] 7.2 Added a "Plate detection" paragraph to `README.md` — covers the `--plate-model {n,s,m}` CLI flag, the Review-page combo-box, the latency warning ("s ≈ 3× slower, m ≈ 8× slower"), and the "try `s` first; only try `m` with a GPU" guidance. Per-variant caching explained so users understand switches are cheap after first download.

## 8. Empirical validation — **superseded by product decision**

Mid-implementation, the user made the product call to flip the default to `"m"` directly (combined with raising the default confidence to `0.20` to offset `m`'s higher false-positive rate at low confidence). The A/B comparison below was therefore skipped: the decision it was meant to inform is already made and encoded in the defaults.

If `m` later turns out to be too slow in practice, rolling back to `"s"` or `"n"` is a one-line default flip in `model_manager.py` + the combo / CLI default.

- [x] 8.1 Superseded — no A/B clip needed; default already flipped to `m`.
- [x] 8.2 Superseded — no n-vs-s-vs-m measurement recorded.
- [x] 8.3 Superseded — decision made directly (default = `m`, threshold = `0.20`).
