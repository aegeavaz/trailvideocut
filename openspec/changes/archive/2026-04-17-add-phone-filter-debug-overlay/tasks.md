## 1. Data model

- [x] 1.1 Add `phone_zones: dict[int, list[tuple[float, float, float, float]]]` field to `ClipPlateData` in `src/trailvideocut/plate/models.py`, defaulting to an empty dict via `field(default_factory=dict)`.
- [x] 1.2 Write a TDD test verifying `ClipPlateData()` default-constructs with an empty `phone_zones` map and that round-tripping a dataclass instance preserves zones.

## 2. Plate detector: record zones

- [x] 2.1 In `src/trailvideocut/plate/detector.py`, extend `_detect_clip_opencv` to write `self._phone_zones[:]` (as a new tuple list, copied) into `result.phone_zones[frame_num]` after `detect_fn(frame)` is called, for every processed frame when `self._exclude_phones` is True.
- [x] 2.2 Ensure zones are also recorded when `_phone_zones` is empty for a given frame by simply skipping the write (no empty entries) — keep the map sparse, as per the spec's "no empty list entry" precedent for detections.
- [x] 2.3 Add a read-only `PlateDetector.current_phone_zones` property returning a copy of `self._phone_zones`, so the single-frame `detect_frame*` call path can expose the active zones to callers.
- [x] 2.4 TDD: unit test that `detect_clip` with `exclude_phones=True` populates `phone_zones` on frames where a phone is detected (use a stub `_phone_model` that returns a fixed box) and leaves it empty when `exclude_phones=False`.
- [x] 2.5 TDD: unit test that the surviving `result.detections` dict is bit-identical between an `exclude_phones=True` run with recording and a baseline that bypasses recording (regression guard for Requirement "Zone recording SHALL NOT alter filtering semantics").

## 3. Worker plumbing

- [x] 3.1 In `src/trailvideocut/ui/workers.py`, verify the existing `ClipPlateData` object already crosses the thread boundary through the result signal; no new signal is required — add a comment noting that `phone_zones` rides along on the same object.
- [x] 3.2 TDD: a smoke test using the existing worker harness (if present, otherwise a minimal test creating a `DetectionWorker` with a stub detector) that asserts the emitted `ClipPlateData` carries the zones dict into the receiving slot.

## 4. Overlay widget: zone rendering

- [x] 4.1 Add `_phone_zones: list[tuple[float, float, float, float]]` state and `_phone_zones_visible: bool = False` flag to `PlateOverlayWidget.__init__` in `src/trailvideocut/ui/plate_overlay.py`.
- [x] 4.2 Add public `set_phone_zones(zones)` / `clear_phone_zones()` / `set_phone_zones_visible(bool)` methods that update state and call `self.update()` only when the stored value actually changes.
- [x] 4.3 In `paintEvent`, after the background fill and before blur tiles + plate boxes, draw each zone when `_phone_zones_visible` is True: dashed 2px pen in `#E040FB`, translucent fill `QColor(224, 64, 251, 30)`, using the existing `_norm_to_widget` transform.
- [x] 4.4 Verify in code review that `mousePressEvent`, `mouseMoveEvent`, `_update_cursor`, `_hit_handle`, and `_handle_right_click` reference only plate-box state (not `_phone_zones`) — zones must be input-inert.
- [x] 4.5 TDD (qtbot): render a 1920x1080-logical widget, call `set_phone_zones([(0.1, 0.2, 0.3, 0.4)])` + `set_phone_zones_visible(True)`, grab the widget image, and assert a pixel at the zone's interior center has the expected magenta RGB component above a threshold.
- [x] 4.6 TDD (qtbot): with zones visible and no plate box at the click point, synthesize a `QMouseEvent` left-click inside the zone and assert `selected_box()` stays None and no "selected" index is assigned to a zone.

## 5. Review page: wire up controls

- [x] 5.1 In `src/trailvideocut/ui/review_page.py`, add a `QCheckBox("Show Phone Filter")` after `_chk_exclude_phones`/`_spin_phone_gap` in `settings_row`, default unchecked and initially disabled.
- [x] 5.2 Connect the checkbox's `toggled` signal to a new `_on_show_phone_filter_toggled` slot that calls `self._plate_overlay.set_phone_zones_visible(checked)` and pushes the current frame's zones if turning on.
- [x] 5.3 Add `_update_show_phone_filter_enabled()` helper that enables the checkbox only when (`_chk_exclude_phones.isChecked()` AND current clip's `plate_data.phone_zones` is non-empty). Call it from: `_chk_exclude_phones.toggled`, clip-selection change, plate-data updates, and clip-plates-cleared.
- [x] 5.4 Extend `_update_plate_overlay_frame` (and the force-set path invoked on clip change) to look up `clip_data.phone_zones.get(frame_num, [])` and call `self._plate_overlay.set_phone_zones(...)` on every frame change, regardless of the checkbox state — so flipping the checkbox shows the already-cached zones immediately.
- [x] 5.5 When disabling the checkbox (conditions no longer met), forcibly uncheck it and call `self._plate_overlay.set_phone_zones_visible(False)`.
- [x] 5.6 TDD (pytest-qt): drive the ReviewPage with a stub `ClipPlateData` containing zones on one frame, verify the checkbox is disabled until `_chk_exclude_phones` is on AND zones exist, and once enabled+checked the overlay receives the right zones on frame navigation.

## 6. Persistence

- [x] 6.1 Extend `src/trailvideocut/plate/storage.py` to serialize `phone_zones` into the `.plates.json` sidecar alongside `detections`. Bump schema version from 1 to 2. Keep v1 files readable (zones default empty).
- [x] 6.2 TDD: round-trip zones through save/load; confirm legacy v1 sidecars still load with empty zones and intact plate detections.

## 7. Integration / smoke

- [ ] 7.1 (manual) Manually run the app against a short video with a visible phone, enable "Exclude Phone", run detection, toggle "Show Phone Filter" on, and confirm the magenta dashed rectangle tracks the phone across frames and disappears when the phone leaves the frame (after the next refresh interval).
- [ ] 7.2 (manual) Manually confirm the checkbox is disabled on a clip that has never been detected, on a clip whose detection ran with `Exclude Phone` off, and re-enables after a fresh detect with `Exclude Phone` on.
- [ ] 7.3 (manual) Manually confirm: selecting, moving, resizing, right-click-adding, and Delete-ing plates all behave identically whether zones are visible or hidden.
- [x] 7.4 Run the full test suite (`pytest`) and any lint/type checks the project uses; fix any regressions.
