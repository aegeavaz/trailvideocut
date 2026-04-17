## 1. Projector module (TDD: tests first)

- [x] 1.1 Create `tests/test_plate_projection.py` with failing unit tests covering: two prior detections → extrapolation, prior+next → interpolation, two next detections → backward extrapolation, single detection → returns `None`, zero detections → returns `None`, frame delta exceeds `max_window` → returns `None`, projected result clamped to `[0, 1]` bounds, size taken from nearest reference.
- [x] 1.2 Create `src/trailvideocut/plate/projection.py` with `project_manual_box(detections, current_frame, *, max_window=60) -> PlateBox | None` implementing linear projection of the box center from two reference samples (preference order: two prior, prior+next, two next) and returning `None` for all fallback cases.
- [x] 1.3 Confirm all tests in `tests/test_plate_projection.py` pass and the module has no Qt imports.

## 2. Wire projector into manual-add flow

- [x] 2.1 In `ReviewPage._on_add_plate` (`src/trailvideocut/ui/review_page.py`), call `project_manual_box` first; on non-`None` result use that box (marked `manual=True`), otherwise fall through to the existing `find_nearest_reference_box` / cursor / center logic.
- [x] 2.2 Verify the projected box is added via `PlateOverlay.add_box` so it is selected and triggers `box_changed` (auto-save path unchanged).
- [ ] 2.3 Manually verify in the running app: on a clip with two prior detections, adding a plate at a later frame places the box near the true plate location instead of the old one; on a clip with zero detections, the cursor/center fallback still works. *(Left for user — cannot be driven from an automated session.)*

## 3. Spec-driven overlay tests

- [x] 3.1 Update or add overlay/review tests covering each scenario in `specs/plate-overlay-ui/spec.md` (projection with two prior, interpolation between prior and next, backward extrapolation, gap exceeds window, only one reference, zero references via right-click, zero references via button, selection after add). *(Projection scenarios covered by `TestProjectManualBoxSpecScenarios` in `tests/test_plate_projection.py`; zero-reference cursor/center fallback and selection-after-add behavior are unchanged and remain covered by existing `tests/test_plate_overlay.py` tests.)*
- [x] 3.2 Run the full test suite (`pytest`) and confirm it passes with no regressions to existing plate-overlay tests. *(462 passed, 11 skipped — GPU-only.)*

## 4. Validate the change

- [x] 4.1 Run `openspec validate project-manual-plate-position` and fix any schema issues.
- [x] 4.2 Run `openspec status --change project-manual-plate-position` and confirm all artifacts are `done`.
