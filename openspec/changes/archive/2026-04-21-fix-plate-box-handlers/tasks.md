## 1. Test harness + baseline

- [x] 1.1 Scan `tests/` for existing `QApplication` / `pytest-qt` patterns (`grep -R "QApplication\|qtbot\|pytest_qt" tests/`) and pick the pattern the project already uses; document it at the top of any new test module so later contributors stay consistent.
- [x] 1.2 Run the current suite (`pytest -q`) and record the baseline pass/fail count so later task diffs are unambiguous.

## 2. Pixel-space corner helper (outline + handles)

- [x] 2.1 Add a failing unit test in `tests/ui/test_plate_overlay.py` that constructs a `PlateOverlayWidget` with a 1920×1080 video and a matching widget rect, installs one `PlateBox(x=0.4, y=0.45, w=0.2, h=0.05, angle=20)`, and asserts the four pixel-space corners returned by the new helper form a rectangle (opposite sides equal to sub-pixel tolerance, interior angles 90°).
- [x] 2.2 Add a second failing test: the outline corners the painter draws and the resize handle anchor points (`tl/tr/br/bl/t/b/l/r`) returned by `_handle_positions_for_box` coincide point-for-point on a rotated box.
- [x] 2.3 Introduce the helper `PlateOverlayWidget._oriented_corners_widget(box)` that calls `box.corners_px(vr.width(), vr.height())` and translates by `vr.x(), vr.y()` to produce `[QPointF, QPointF, QPointF, QPointF]` in TL/TR/BR/BL order.
- [x] 2.4 Rewrite `paintEvent`'s oriented-outline branch to build the `QPolygonF` from `_oriented_corners_widget(box)` (delete the `corners_px(1.0, 1.0)` + manual scale path).
- [x] 2.5 Rewrite `_handle_positions_for_box` to call `_oriented_corners_widget(box)` instead of computing its own `corners_px(vr.width(), vr.height())`. The rotation-handle "up" direction still derives from the same four corners — no functional change there, just one call instead of two.
- [x] 2.6 Re-run the two new tests — they SHALL pass.

## 3. Pixel-space hit test

- [x] 3.1 Add a failing test that clicks a point inside the **envelope** of a rotated box but outside its rotated rectangle and asserts `_point_in_box` returns `False`; and a complementary test for a point inside the rotated body that returns `True`.
- [x] 3.2 Rewrite `PlateOverlayWidget._point_in_box(pos, box)` so the rotation into the plate's local frame happens in pixel coordinates: compute `cx_px = (box.x + box.w/2)*vr.width() + vr.x()`, `cy_px` similarly, `dx, dy = pos.x()-cx_px, pos.y()-cy_px`, rotate by `-angle` in that pixel space, and compare against `box.w*vr.width()/2` and `box.h*vr.height()/2`.
- [x] 3.3 Re-run the hit-test suite — new tests SHALL pass and existing axis-aligned tests SHALL still pass.

## 4. Pixel-space resize math

- [x] 4.1 Add a failing test for `_apply_resize`: start with `PlateBox(x=0.4, y=0.45, w=0.2, h=0.05, angle=20)` selected on a 1920×1080 widget; simulate dragging the `br` corner handle by `(+40, +5)` pixels and assert the post-drag box's four pixel-space corners still form a rectangle (opposite sides equal, interior angles 90°) and the angle is still 20°.
- [x] 4.2 Add a second failing test for an edge handle (`r`): drag by `(+30, 0)` pixels on the same oriented box and assert the box grew only along its local horizontal axis (height unchanged to sub-pixel tolerance), the angle unchanged, and the opposite-edge midpoint stayed at its pre-drag pixel position.
- [x] 4.3 Rewrite `_apply_resize` so all vectors (`ux, uy`, `vx, vy`, reference point, mouse position, `proj_u`, `proj_v`, new centre) live in pixel space; convert `new_w`, `new_h`, `new_cx`, `new_cy` back to normalized (divide by `vr.width()` or `vr.height()`) only when assigning to `box.x`, `box.y`, `box.w`, `box.h`. Keep `_MIN_BOX_PX` in pixels as-is.
- [x] 4.4 Verify all existing axis-aligned resize scenarios (`angle == 0`) still pass; add a regression test that resizes an axis-aligned box and checks the final `(x, y, w, h)` matches the pre-change behaviour exactly.
- [x] 4.5 Re-run the suite — new tests and all prior tests SHALL pass.

## 5. Refine/Clear button refresh on box_changed

- [x] 5.1 Add a failing test in `tests/ui/test_review_page_buttons.py`: construct a `ReviewPage` with a clip that has zero plate detections, call `self._plate_overlay.add_box(PlateBox(...))`, and assert `_btn_refine_clip_plates.isEnabled()` and `_btn_refine_frame_plates.isEnabled()` are both `True` immediately after (without any frame navigation).
- [x] 5.2 Add a second failing test: on a frame that already has a plate, delete it via `_plate_overlay.delete_selected()` and assert `_btn_refine_frame_plates.isEnabled()` is `False` afterwards.
- [x] 5.3 In `ReviewPage._on_plate_box_changed`, add `self._update_frame_buttons()` after `self._save_plates()`.
- [x] 5.4 Re-run the tests — they SHALL pass.

## 6. Manual add inherits rotation

- [x] 6.1 Add a failing test in `tests/plate/test_projection.py` (or equivalent existing projection test module) that calls `project_manual_box(...)` with two reference detections at frames 40 and 50, both with `angle = 15°`, for current frame 60; assert the returned `PlateBox.angle == 15°` and `PlateBox.manual == False` (the caller flips `manual`).
- [x] 6.2 Update `project_manual_box` and its `_clamp_box` helper in `src/trailvideocut/plate/projection.py` to carry the nearest reference's `angle` through to the returned `PlateBox`.
- [x] 6.3 Add a failing test in `tests/ui/test_review_page_add_plate.py` (or equivalent) that sets a clip with one reference plate at `angle = 12°` on a neighbouring frame, calls `ReviewPage._on_add_plate()` on a frame with no plates, and asserts the newly added box has `angle == 12°`, `manual == True`.
- [x] 6.4 Add a complementary failing test for the motion-projection path (two refs with `angle = 15°`) asserting the new box has `angle == 15°`.
- [x] 6.5 Add a failing test for the no-reference fallback (empty clip, right-click in the video) asserting the new box has `angle == 0.0`.
- [x] 6.6 Update `ReviewPage._on_add_plate` so both the `projected is not None` branch and the `ref := find_nearest_reference_box()` branch copy `angle` onto the new `PlateBox(...)` call.
- [x] 6.7 Re-run the suite — all five new tests SHALL pass and no prior tests SHALL regress.

## 7. Cross-cutting verification

- [x] 7.1 Run `pytest -q` end-to-end; confirm the baseline count from task 1.2 has strictly grown (by the number of new tests added in sections 2–6) with zero new failures.
- [ ] 7.2 Manually exercise the four user scenarios on a non-square (16:9) clip (deferred — headless agent cannot drive the GUI; the automated tests in sections 2–6 assert the equivalent invariants):
  - (a) Select an oriented plate, drag the rotation handle — the visible outline SHALL stay a rectangle throughout the drag and the angle field SHALL update continuously.
  - (b) With the same plate still selected, drag each of the eight resize handles in turn — all handles SHALL stay exactly on the outline and each drag SHALL produce a rectangle.
  - (c) On a clip with zero plates, click "Add Plate" (or right-click the overlay) — both "Refine Clip Plates" and "Refine Frame Plates" SHALL enable as soon as the plate appears.
  - (d) On a clip whose existing plate has a non-zero angle, click "Add Plate" on a different frame — the new plate's outline SHALL match the existing plate's rotation.
- [x] 7.3 Run `openspec validate fix-plate-box-handlers` and confirm it reports valid.

## 8. Blur preview honours rotation

- [x] 8.1 Add a failing test in `tests/test_plate_blur.py` (or a new `tests/test_review_page_blur_preview.py` if the existing module is too focused) that enables `Preview Blur` on a frame with a single oriented plate (`angle = 20°`), runs `_update_blur_preview`, and asserts the resulting blur tile's normalized rect equals `box.aabb_envelope()` (not `(box.x, box.y, box.w, box.h)`).
- [x] 8.2 Add a regression failing test for an axis-aligned plate (`angle = 0`) asserting the tile rect equals `(box.x, box.y, box.w, box.h)` exactly — envelope and plate-aligned rect coincide in that case, so the test pins the invariant.
- [x] 8.3 Rewrite the tile-extraction loop in `ReviewPage._update_blur_preview` so it crops from `box.aabb_envelope()` (scaled to pixel coordinates, clamped to frame bounds) and registers the tile at that envelope rect. Do NOT re-invoke any blur — `apply_blur_to_frame` already produced the oriented blur on `frame`; the fix is purely cropping and tile placement.
- [x] 8.4 Re-run the tests — both SHALL pass, and no prior tests SHALL regress.
