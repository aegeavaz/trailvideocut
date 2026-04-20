## Context

Earlier work (archived change `2026-04-18-fix-automatic-plate-position-displacement`) pivoted keyboard frame-stepping from leading-edge seek targets to centre-of-window seek targets through the helper `VideoPlayer._frame_center_ms(frame)`:

```python
def _frame_center_ms(self, frame: int) -> int:
    if frame <= 0:
        return 0
    return int((frame + 0.5) * 1000.0 / self._fps)
```

The fix was motivated by an observed ~8 ms presentation-timestamp (PTS) offset at 23.976 fps on H.264/HEVC sources, large enough that a seek targeting `frame * 1000 / fps` can fall inside the *previous* frame's actual display window — the decoder stays put while `QMediaPlayer.position()` and the overlay advance.

`seek_to` was never updated. It is still:

```python
def seek_to(self, seconds: float):
    self._seek(int(seconds * 1000))          # video_player.py:257-258
```

Every caller — Review-page clip click (`_on_clip_selected`, `review_page.py:819,839`), preview re-seek (`review_page.py:696,713`), Setup-page mark jump (`setup_page.py:321`) — goes through this one helper, so all of them inherit the same off-by-one when the target seconds lands near a frame boundary.

The `frame_math.position_to_frame(pos_s, fps) = int(pos_s * fps + 1e-9)` helper is already the project's canonical seconds → source-frame mapping and drives `VideoPlayer.frame_at`. Reusing it here keeps `seek_to`'s frame resolution consistent with the frame label, overlay, and plate storage keys.

## Goals / Non-Goals

**Goals:**
- Make `VideoPlayer.seek_to(seconds)` land the decoder on the same source frame that the frame label / overlay report, for any realistic container PTS offset.
- Fix every caller in one spot by keeping the centre-of-window arithmetic inside `seek_to` (no call-site churn).
- Share the arithmetic with `_step_forward` / `_step_back` so a future change to the centre formula only has to touch one helper.
- Add regression coverage that pins the behaviour to the scenarios in the `frame-precise-navigation` spec.

**Non-Goals:**
- Exposing a new public API (`seek_to_frame`, etc.) or changing the signature of `seek_to`.
- Revisiting how `clip.source_start` / `clip.source_end` are computed upstream — the displacement is a seek-time problem, not a clip-boundary problem.
- Backend-level fixes (probing the container's actual PTS offset and subtracting it) — the centre-of-window heuristic already guarantees correctness for offsets smaller in magnitude than `500 / fps` ms, which covers every real-world H.264/HEVC source we have seen.

## Decisions

### Decision: rewire `seek_to` through the existing `_frame_center_ms` helper, not introduce a new path

```python
def seek_to(self, seconds: float):
    frame = position_to_frame(max(seconds, 0.0), self._fps)
    target_ms = self._frame_center_ms(frame)
    self._seek(min(target_ms, self._duration_ms))
```

**Why:** the `frame-precise-navigation` spec already mandates centre-of-window targeting for stepping; `seek_to` is conceptually the same operation ("land on the frame the caller asked for"), so they should share the helper. Reusing `_frame_center_ms` keeps the one critical formula in one place.

**Alternatives considered:**
- *Leave `seek_to` alone and add a `seek_to_frame(frame)` variant and have callers convert.* Rejected — pushes the centre-of-window concern into three unrelated call sites (Review, Preview, Setup) and leaves the naive path as a foot-gun for future callers.
- *Add an epsilon to the naive `int(seconds * 1000)` computation.* Rejected — the leading-edge target is still inside the previous frame's PTS window for realistic offsets; the only robust fix is to target the centre.
- *Introduce a new backend that probes actual PTS from the decoder before seeking.* Rejected as over-engineering; centre-of-window already covers every observed case and the existing stepping path relies on the same guarantee.

### Decision: resolve `seconds` → frame via `utils.frame_math.position_to_frame`, not a fresh formula

The function already exists, is already the canonical seconds → frame mapping (`VideoPlayer.frame_at` uses it), and carries the `1e-9` epsilon that prevents float round-trip drift from pushing a boundary-valued seconds into the wrong frame.

**Alternatives considered:**
- *Inline `int(seconds * self._fps)`.* Rejected — loses the 1e-9 epsilon that protects against `4.1 s * 30 fps = 122.999…` truncating to frame 122.

### Decision: clamp to `[0, duration_ms]` inside `seek_to`

Matches the clamps `_step_forward` / `_step_back` perform with `min(..., self._duration_ms)` / `max(..., 0)`. Keeps out-of-range seconds values safe without forcing every caller to clamp.

## Risks / Trade-offs

- [Risk] Existing callers pass `clip.source_end` or `expected_source_pos` values that sit near a frame boundary; shifting the landing position by up to half a frame could surface subtle timing expectations elsewhere.
  → Mitigation: `clip.source_end` is never passed to `seek_to` (it drives `_active_clip_end`, a playback-time boundary check). `expected_source_pos` is already rounded to frame granularity upstream. Regression tests pin the concrete ms values at 23.976 / 29.97 fps so any upstream shift shows up in CI.

- [Risk] Tests mocking `VideoPlayer` that assert a specific `_seek(ms)` value from `seek_to` would drift.
  → Mitigation: search the test suite; update any expectation to the new centre-of-window ms. The only production call sites assert on observable frame state, not raw ms.

- [Risk] Very low FPS sources (≤ 10 fps) could see the centre-of-window target land ≥ 50 ms past the requested seconds, perceptible as a "late" clip start.
  → Mitigation: the off-by-one is visually obvious; a ≤ half-frame late start is not. This is the same trade already accepted by keyboard stepping, and the `frame-precise-navigation` spec already documents the bound (`|offset| < 500 / fps` ms).

## Migration Plan

Single-commit behaviour change; no data or schema migration. Rollback is reverting the `seek_to` body to `self._seek(int(seconds * 1000))`.
