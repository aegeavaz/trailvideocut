## Context

Today `ReviewPage._on_add_plate` calls `PlateOverlay.find_nearest_reference_box()` and clones its `x, y, w, h` verbatim. That function returns the first box from the closest frame (backward preferred, then forward). On moving trail footage the plate has usually drifted by the time the user pauses to manually annotate a frame that the detector missed, so the cloned box lands at the *old* plate position and the user has to drag it into place every time.

The detection dictionary is sparse (`ClipPlateData.detections: dict[int, list[PlateBox]]`) — typically a few detections per second on trail clips with gaps where the plate was blurred or occluded. We have enough signal on either side of a missed frame to estimate where the plate *should* be now with a simple motion model.

Constraints:
- Normalized coordinates (0–1) throughout.
- Must not introduce a Qt dependency in the math layer (rest of `plate/` is Qt-free and we want the projector unit-testable without a display).
- Must preserve existing fallbacks (cursor placement, frame center) for the zero-detection case.
- Follow SOLID; existing code puts math in `plate/` (see `temporal_filter.py`) and wiring in `ui/`.

## Goals / Non-Goals

**Goals:**
- When adding a manual plate on a frame with no detection, place the new box close to the true plate position using recent detections.
- Keep the projector a pure function, easy to test with TDD.
- Preserve behavior for all existing fallback paths (no detections, only one detection, no cursor).

**Non-Goals:**
- Not a tracker. We do not re-run on every frame or modify detected boxes.
- No Kalman filter, no per-box identity matching across frames, no acceleration model.
- No change to the detector, sidecar format, blur pipeline, or export pipeline.
- Not extrapolating box size — trail plates maintain roughly stable apparent size over a short window, and interpolating width/height adds noise without visible benefit.

## Decisions

### Decision 1: Linear projection of box center from two reference samples

Use the two reference detections closest to the current frame to estimate a per-frame velocity `(dvx, dvy)` of the box center, then project that velocity across the frame delta to the current frame. Box size is taken from the nearest reference (not projected).

Preference order for the two samples:
1. Two closest prior detections (extrapolate forward).
2. One prior + one next detection (interpolate across the gap).
3. Two closest next detections (extrapolate backward).

If only one sample exists, fall back to cloning it (matches current behavior). If zero, fall back to cursor/center placement (matches current behavior).

**Why linear over higher-order or Kalman:** Detections are sparse and noisy; a 2-point linear model is the simplest thing that captures the dominant signal (the camera/plate is moving steadily). Higher-order fits amplify noise. A Kalman filter would require per-box identity tracking across frames, which we don't have and don't want to build for a manual-add UX helper.

**Alternatives considered:**
- *Clone nearest and let the user drag* (status quo) — reliable but annoying; rejected because the whole point of this change is to remove the drag.
- *Mean of last N detections* — ignores motion direction; would bias toward the past.
- *Kalman / optical flow per frame* — much more complex, requires identity tracking, overkill for a UX nudge.

### Decision 2: Cap the projection by a frame-window threshold

Define `MAX_PROJECTION_WINDOW_FRAMES` (default **60 frames**, ≈2s at 30fps). If either chosen reference frame is further than this window from the current frame, skip projection and fall back to cloning the nearest single reference. This protects against wild extrapolation across long detection gaps (e.g., a full tunnel).

**Why 60 frames:** Long enough to bridge realistic detector gaps on trail footage without projecting so far that accumulated velocity error dominates. Configurable in one place; can be tuned once we dog-food.

### Decision 3: Module placement — new `plate/projection.py`

Put the pure-Python projector in `src/trailvideocut/plate/projection.py` with a single public function, roughly:

```python
def project_manual_box(
    detections: Mapping[int, list[PlateBox]],
    current_frame: int,
    *,
    max_window: int = 60,
) -> PlateBox | None:
    """Return a projected PlateBox for current_frame, or None to signal fallback."""
```

The overlay stays responsible for Qt concerns (cursor position, selection, repaint). `ReviewPage._on_add_plate` calls the projector first; on `None`, it falls through to the existing `find_nearest_reference_box` / cursor / center logic already in place.

**Why a new module:** Single Responsibility — projection math is distinct from rendering or data storage. Dependency Inversion — the overlay depends on a function, not on any ML/Kalman machinery. Mirrors the layout of `plate/temporal_filter.py`, which is the existing precedent for pure-math helpers in this package.

### Decision 4: Choose one representative box per reference frame

A frame can contain multiple detected boxes. For the projector we pick **the first box** in each reference frame's list (matching the current `find_nearest_reference_box` semantics). This keeps behavior predictable in single-plate clips (the common case) and avoids building a matching algorithm that this change doesn't need.

If multi-plate support is required later, the projector signature already accepts the full detections map and can be extended to take a "pick" strategy without breaking callers.

### Decision 5: Clamp the projected box to frame bounds

After projecting, clamp `(x, y)` so that `x + w <= 1` and `y + h <= 1` and `x, y >= 0`. This matches how drag-moved boxes are clamped elsewhere in the overlay and prevents the new box from being partially invisible.

## Risks / Trade-offs

- **Risk:** Linear projection overshoots when the plate decelerates or turns sharply.
  **Mitigation:** `MAX_PROJECTION_WINDOW_FRAMES` bounds the extrapolation distance; worst case the user still drags a little. Acceptable — the new box is at least as good as the status quo, and usually much better.

- **Risk:** Picking "first box in frame" confuses multi-plate clips.
  **Mitigation:** Matches current behavior; not a regression. Documented as an explicit non-goal.

- **Risk:** A user tunes up expectations and complains when projection is skipped for long gaps.
  **Mitigation:** The fallback is the existing clone behavior, so worst case is status quo. We can surface the threshold as a config later if needed.

- **Trade-off:** Keeping box size constant (not projected) means the projector can't compensate for a plate visibly shrinking as it recedes. Deliberate — width/height signal is too noisy on two samples, and the user can resize once.

## Migration Plan

No data migration. The change is purely in the add-plate code path. Rollback: revert the `_on_add_plate` call site and delete the new module; no persisted artifact depends on it.
