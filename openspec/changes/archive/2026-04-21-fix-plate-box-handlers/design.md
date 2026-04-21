## Context

`PlateOverlayWidget` supports oriented plate boxes via the `angle` field on `PlateBox`. Rotation was introduced by the refiner (`plate/refiner.py` uses `cv2.minAreaRect` in pixel space and stores `w, h` as `w_px / frame_w` and `h_px / frame_h`), so the semantic of `(w, h)` is "plate-aligned extent expressed as a fraction of the video's pixel width and pixel height respectively" and `angle` is "rotation in video pixel space".

The overlay mostly honours that semantic — `PlateBox.corners_px(widget_w, widget_h)` already multiplies half-widths/heights by the pixel canvas before rotating, so handle positions in `_handle_positions_for_box` are correct. Two places break the semantic:

1. `PlateOverlayWidget.paintEvent` draws the oriented outline using `box.corners_px(1.0, 1.0)` and then multiplies the resulting (normalized) corners by `vr.width()` / `vr.height()` separately. That scaling-after-rotation skews the rectangle into a parallelogram whenever `vr.width() != vr.height()` (which is the typical case — 16:9 video yields `vr` ≈ 1920×1080).
2. `_apply_resize` builds the plate's local axes as unit vectors in normalized coordinates (`ux, uy = cos, sin`), then reconstructs the box with positions mixed between those normalized axes and the normalized reference point. Because the normalized `x` and `y` units are not the same length in pixels, the projection of mouse motion onto those axes is wrong except at `angle ∈ {0°, 90°, 180°, 270°}`, and the resulting `(w, h)` no longer produces a rectangle on drag.
3. `_point_in_box` has the same defect (hit-test rotation is done in normalized space), so clicks near the rotated corners miss and clicks in the envelope's empty triangles can (rarely) hit.

Two orthogonal issues live in `ReviewPage`:

4. `_on_plate_box_changed` (wired to `PlateOverlayWidget.box_changed`) calls `_refresh_plate_list()` and `_save_plates()` but not `_update_frame_buttons()`. When a clip goes from having no plates to having one via `add_box`, the Refine and Clear buttons never get re-evaluated until the user navigates away (which triggers `_on_position_changed` → `_update_frame_buttons`).
5. `_on_add_plate` constructs new `PlateBox(...)` instances from `projected` or from `find_nearest_reference_box()` but only copies `x, y, w, h`; `angle` defaults to `0.0`. `project_manual_box` returns a box whose angle is already lost (`_clamp_box` creates a fresh `PlateBox` without an angle argument either).

## Goals / Non-Goals

**Goals:**
- Unify oriented-box rendering and handle positioning on a single pixel-space geometry source so the outline and the handles cannot drift.
- Do all resize/hit-test rotation math in pixel space so drags on oriented boxes produce true rectangles on any video aspect ratio.
- Propagate the signal "the plate set of the current clip/frame changed" to button-state refresh, so Refine/Clear buttons enable immediately after the first add.
- Inherit `angle` from the reference detection used to seed a manual add (projection or nearest-reference clone), so neighbouring rotations carry through.
- Ship every fix under TDD — add a failing test first (or adapt an existing one), then fix the code.

**Non-Goals:**
- No change to `PlateBox` data shape or to sidecar format. `angle` is already persisted.
- No change to how the refiner computes the angle.
- No change to the rotation-handle cursor or to the set of handles drawn.
- No generalisation of the overlay to non-rectangular shapes (the plate is always an oriented rectangle).

## Decisions

### Decision 1 — Single pixel-space corner source

Introduce a private helper on `PlateOverlayWidget` that returns the four oriented corners **in widget pixel coordinates** for a given `PlateBox`, and route both the outline rendering and the handle placement through it. This replaces:

- `paintEvent`'s `box.corners_px(1.0, 1.0)` + manual `vr.width()/vr.height()` scaling.
- The duplicated `box.corners_px(vr.width(), vr.height())` call in `_handle_positions_for_box`.

**Why**: A single source of truth prevents the two paths from drifting again. The helper is tiny (one call to `box.corners_px(vr.width(), vr.height())` plus `vr.x() / vr.y()` offset), so it pays for itself.

**Alternative considered**: Fix `paintEvent` inline to call `box.corners_px(vr.width(), vr.height())` and add `vr.x()/vr.y()`, leave `_handle_positions_for_box` alone. Rejected because the two paths would still be independent code with the same duty — an SRP-style violation that was part of why the bug existed in the first place.

### Decision 2 — Pixel-space resize math

Rewrite `_apply_resize` so the reference point, the plate's local axes, and the mouse position are all expressed in pixel space (widget coordinates inside `vr`), and convert `(new_w, new_h, new_cx, new_cy)` back to normalized (`/vr.width()`, `/vr.height()`) **only** when writing back to the `PlateBox`. The local axes become proper unit vectors in pixel space (`ux, uy = cos(rad), sin(rad)`), and the projection `proj_u = rx*ux + ry*uy` is the true plate-horizontal extent in pixels.

Minimum-size clamp is already expressed in pixels (`_MIN_BOX_PX`) — it stays the same.

**Why**: The `angle` semantic is "rotation in pixel space", so the math must live there. Expressing the reference point in pixel space also makes the clamp-to-frame logic more natural (compare against `vr.width()` / `vr.height()` instead of `1.0`).

**Alternative considered**: Keep the math in normalized space but scale the local axes by `(vr.width(), vr.height())` per use. Rejected — it obscures intent and makes the code harder to reason about than "project a pixel vector onto a pixel unit vector". The normalized-space version is the source of the bug; keeping it invites regression.

### Decision 3 — Pixel-space hit test

Rewrite `_point_in_box` to:
- Map `pos` into pixel coordinates relative to `vr.topLeft()`.
- Compute the box centre in pixel coordinates (`cx_px`, `cy_px`).
- Rotate the offset into the plate's local frame using pixel-space half-widths (`box.w * vr.width() / 2`, `box.h * vr.height() / 2`).

**Why**: Same rationale as Decision 2 — the rotation is in pixel space, so the point-in-oriented-rectangle test must live there.

### Decision 4 — `_on_plate_box_changed` refreshes button state

Add `self._update_frame_buttons()` to `ReviewPage._on_plate_box_changed` (and, for symmetry, ensure other add/delete code paths that bypass `box_changed` either emit it or call `_update_frame_buttons` themselves — audit shows `delete_selected` already emits `box_changed`).

**Why**: `box_changed` is the overlay's single "the plate set mutated" signal and the review page is the only listener that owns button state. Refreshing on every edit is cheap (the method is pure button-state bookkeeping, no I/O).

**Alternative considered**: Only refresh on the first add, via a one-shot guard. Rejected because mutations from resize/rotate/move don't change the enablement state, so the extra `_update_frame_buttons` call is a no-op in those cases, and the unconditional call is simpler and robust against future state-dependent buttons.

### Decision 5 — Inherit `angle` on manual add

Three places need to copy `angle`:

1. `ReviewPage._on_add_plate` — when constructing from `projected` or from `find_nearest_reference_box()`, pass the reference's `angle`.
2. `plate/projection.py` `project_manual_box` and its `_clamp_box` helper — the returned `PlateBox` must carry the nearest reference's `angle` so the review page can read it back. Currently `_clamp_box` drops angle by constructing `PlateBox(x, y, w, h)` with defaults.

**Why**: The projection helper's docstring says the returned box is "geometry only" and leaves `manual` to the caller — angle is part of that geometry and should be part of the returned shape. The review page is the right layer to apply the `manual=True` flag; it's not the right layer to re-discover the reference's angle.

**Alternative considered**: Leave `project_manual_box` alone and read the nearest reference's angle separately in the review page. Rejected because it duplicates the nearest-reference selection logic that already lives inside `project_manual_box` (and because the "nearest reference" for size in that helper is a specific choice that the review page would have to replicate bit-for-bit).

### Decision 6 — Tests live at the unit boundary

Put the oriented-geometry tests in `tests/ui/test_plate_overlay.py` using `pytest-qt` (already in the test suite based on file list convention) or by directly constructing `PlateOverlayWidget` with `QApplication` in a fixture. Each test should:

- Construct a widget, set a fixed `video_size` (e.g. 1920×1080) and a fixed widget size so `vr` is deterministic.
- Install a `ClipPlateData` with a single known oriented box and verify:
  - The four corners returned by the new corner helper form a rectangle in pixel space (opposite sides equal, interior angles 90°).
  - `_point_in_box` returns `True` for the centre and `False` for a point inside the envelope but outside the rotated rect.
  - After calling `_apply_resize` with a handle and a mouse delta, the resulting box's pixel corners still form a rectangle and the angle is unchanged.

Projection and `_on_add_plate` tests go in `tests/ui/test_review_page_add_plate.py` (or adjacent), exercising:
- Projection from two refs with angle=15° yields a box whose angle is 15°.
- Nearest-reference clone inherits angle.
- No-reference fallback gives angle=0.

Refine-button refresh tests go in `tests/ui/test_review_page_buttons.py` (or adjacent):
- Adding the first plate via `PlateOverlayWidget.add_box` triggers an enabled state on `_btn_refine_clip_plates` and `_btn_refine_frame_plates`.

**Why**: Unit-level tests keep iteration fast and pinpoint regressions to the exact component. Qt tests that need an event loop use `pytest-qt`'s `qtbot` fixture if available, or a plain `QApplication.instance() or QApplication(sys.argv)` bootstrap otherwise (both patterns already exist elsewhere in the repo — the task list will verify which to use).

## Risks / Trade-offs

- **Risk**: Re-interpreting the resize math may change sub-pixel behaviour for axis-aligned boxes (`angle == 0`). **Mitigation**: Verify the axis-aligned scenarios in the existing spec (corner-handle drag, edge-handle drag, min-size clamp) are preserved by running the full overlay test suite; add a regression test that resizes an axis-aligned box and checks the result byte-for-byte against the pre-change implementation.
- **Risk**: Tests for the widget require a running `QApplication`, which can be flaky on headless CI. **Mitigation**: Use the same headless pattern the repo already uses (look for existing `QApplication`/`pytest-qt` patterns before adding our own).
- **Risk**: `project_manual_box` is used beyond `_on_add_plate`; changing its return value could touch other callers. **Mitigation**: grep for callers and verify the extra `angle` on the returned box is additive — callers that construct a new `PlateBox` from `projected.x/y/w/h` will simply ignore `angle` unless we explicitly propagate it. Net effect is backward-compatible.
- **Risk**: Extra `_update_frame_buttons` calls during a drag (fired on every `box_changed`) could be wasteful. **Mitigation**: `box_changed` is emitted on `mouseReleaseEvent`, not during the drag — one call per completed edit is already the current cadence.

## Open Questions

- Should the rotation-handle line (the short line from the top-centre to the rotation handle) be drawn using the same new pixel-space "up" direction? Yes — the current code already derives `up` from `_handle_positions_for_box`, which uses pixel space, so no additional work; listing here just to note it's covered by Decision 1.
- Is the `_clamp_box` helper in `projection.py` actually dropping angle for any existing workflow that relies on an axis-aligned result? Audit shows no; the only consumer is `_on_add_plate`, which currently drops the angle anyway. Safe to add `angle` pass-through.
