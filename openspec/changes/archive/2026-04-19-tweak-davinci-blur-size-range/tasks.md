## 1. Update tests first (TDD)

- [x] 1.1 In `tests/test_resolve_script.py`, change the hard-coded midpoint assertion in `TestRelativeBlurSize.test_intermediate_area_gets_interpolated_value` from `abs(vals[1] - 1.5) < 1e-9` to `abs(vals[1] - 2.0) < 1e-9` (the midpoint of the new `[1.5, 2.5]` range).
- [x] 1.2 In `tests/test_resolve_script.py`, refresh any docstrings / comments that read "smallest plate -> 1.0, largest -> 2.0" in `TestRelativeBlurSize` so they describe the new range. (Existing assertions already reference `_BLUR_SIZE_MIN` / `_BLUR_SIZE_MAX` and will remain correct.)
- [x] 1.3 Add a new test in `tests/test_resolve_script.py` (or near the existing in-Resolve script body assertions) that builds the embedded `apply_blur_for_clip` script body and asserts the floor literal in the per-frame loop is `1.5` (e.g. by searching for the substring `1.5 + (box_area - min_area) / area_span`) and the all-equal fallback also reads `1.5`. This guards against the offline generator and the in-Resolve script body drifting apart.
- [x] 1.4 Run `.venv/bin/python -m pytest tests/test_resolve_script.py -k "BlurSize or blur_size or RelativeBlur"` and confirm all the modified / new assertions FAIL against the current (1.0 / 2.0) implementation. Capture the failures as evidence the tests are exercising the right thing.

## 2. Update the offline Lua-script generator

- [x] 2.1 In `src/trailvideocut/editor/resolve_script.py`, change the module constants:
  - `_BLUR_SIZE_MIN = 1.0` → `_BLUR_SIZE_MIN = 1.5`
  - `_BLUR_SIZE_MAX = 2.0` → `_BLUR_SIZE_MAX = 2.5`
- [x] 2.2 Refresh the doc comment immediately above the constants ("Smallest plate in a clip -> _BLUR_SIZE_MIN, largest -> _BLUR_SIZE_MAX") if it cites the old numeric values; keep the symbolic reference intact.
- [x] 2.3 Refresh the `_compute_blur_sizes` docstring if it cites `1.0` / `2.0` literally. (Already symbolic — no edit needed.)

## 3. Update the in-Resolve embedded Python script body

- [x] 3.1 In the embedded `apply_blur_for_clip` body inside `src/trailvideocut/editor/resolve_script.py` (around the "Auto-scaled blur size" comment), change the per-frame interpolation literal from `1.0 + (box_area - min_area) / area_span` to `1.5 + (box_area - min_area) / area_span`.
- [x] 3.2 In the same embedded body, change the all-equal-areas fallback `blur_size = 1.0` to `blur_size = 1.5`.
- [x] 3.3 Update the comment line "Auto-scaled blur size: smallest plate area -> 1.0, largest -> 2.0" and the surrounding docstring fragment "smallest plate -> 1.0, largest -> 2.0" to reflect the new `[1.5, 2.5]` range.

## 4. Validate

- [x] 4.1 Run `.venv/bin/python -m pytest tests/test_resolve_script.py` and confirm the full file passes. (36/36 passing.)
- [x] 4.2 Run the full test suite `.venv/bin/python -m pytest` to confirm nothing else regresses. (476 passed, 11 skipped, 0 failed.)
- [x] 4.3 Run `openspec validate tweak-davinci-blur-size-range --strict` and resolve any warnings/errors. (Valid.)
- [x] 4.4 Manually re-export a small clip with plate blur to DaVinci (or inspect a freshly generated `_resolve_plates.py`) and confirm the emitted XBlurSize keyframes lie in `[1.5, 2.5]`. _(User-verified.)_
