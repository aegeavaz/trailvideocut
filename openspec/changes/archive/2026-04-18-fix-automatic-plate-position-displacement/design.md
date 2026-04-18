## Context

The bug was reported as "automatic plate detection position is wrong after navigation". Initial hypothesis was a frame-key mismatch in `ClipPlateData.detections`. That was ruled out by instrumenting the dict keys against decoded frame indices: detection stored the correct keys, and the overlay correctly looked them up.

Further instrumentation of `QVideoSink.videoFrameChanged` against `QMediaPlayer.position()` revealed the real mechanism. Representative observations (from the user's 23.9754-fps H.264 source):

```
# Click clip (large seek)
setPosition=250000  player_pos=250.000s  player_frame_at=5993
sink: startTime=249.9723s → sink_frame=5993              # aligned

# Step forward (→ arrow, old math)
setPosition=250006 (= ceil(5994 * 1000 / fps))
player_pos=250.006s player_frame_at=5994
sink: startTime=249.9723s → sink_frame=5993              # sink did not advance
                                                         # overlay draws 5994's box over 5993's pixels
# Step back (← arrow, old math)
setPosition=249965 (= ceil(5993 * 1000 / fps))
player_pos=249.965s player_frame_at=5993
sink: startTime=249.9305s → sink_frame=5992              # sink overshot backwards
```

The decoder's frame windows (derived from the videoFrameChanged `startTime`):

- frame 5992 : [249.9305 s, 249.9723 s)
- frame 5993 : [249.9723 s, 250.0141 s)
- frame 5994 : [250.0141 s, 250.0559 s)

versus what the ideal math places them at:

- frame 5992 : [249.923 s, 249.964 s)
- frame 5993 : [249.964 s, 250.006 s)
- frame 5994 : [250.006 s, 250.048 s)

Every container frame is shifted ~8 ms later than the ideal model. The step code seeks to the ideal *boundary* (`ceil(N * 1000 / fps)`), which for forward steps falls inside the previous frame's actual window, so the decoder sees no frame crossing and skips re-decode. For backward steps the ideal boundary falls one frame earlier than intended in the real window, landing on N-1.

After the same instrumentation confirmed the pattern across many frames and both directions, the fix became obvious: target a position that is unambiguously inside the *target* frame's actual window, regardless of the container's presentation offset.

Stakeholders: end users whose automatic plate blur was being applied to the wrong position, making the privacy blur miss the plate.

## Goals / Non-Goals

**Goals:**

- Frame-step in either direction lands the QVideoSink on the requested frame for realistic H.264/HEVC presentation offsets (observed <10 ms; margin ~21 ms at 23.976 fps).
- Overlay box and video pixels agree on the same frame after any step or step round-trip.
- Zero impact on detection storage, overlay rendering, and export pipeline (those were never broken).
- Zero persistence migration — all existing sidecar plate data remains valid.

**Non-Goals:**

- Support for containers with >21 ms constant presentation offset. Unseen in practice; out of scope.
- Any change to `position_to_frame` / `frame_to_position_ms`. Those helpers are correct for their boundary-based uses (detection keys, slider conversion).
- Changes to batch or single-frame detection, plate overlay coordinate math, or MoviePy export. Evidence from instrumentation showed those operate on correct data.
- Fixing the separately-reported export-side displacement. The user's "exported video shows all automatic plates displaced" complaint was observed before this fix. Once this preview fix lands, re-verify with a fresh export and investigate separately if still present — it may have been the same bug manifesting in the preview they used to judge correctness.

## Decisions

### Decision 1: Seek to the center of the target frame's ideal window

`_step_forward` and `_step_back` compute target ms as `int((target_frame + 0.5) * 1000.0 / fps)` via a new private helper `_frame_center_ms`. At the ideal (math) level, this places the position at the midpoint of frame N's ideal window, giving half a frame of margin on each side. In the real (container) frame window, which is shifted by some offset O from ideal, the position still lies inside the target frame's window as long as `|O| < frame_duration / 2` (≈ 20.85 ms at 23.976 fps).

- Alternative considered: query `QVideoSink.videoFrame().startTime()` on each step and compute the target as `current_startTime + frame_duration` (sink-relative stepping). Rejected because it couples frame-step behavior to a signal that is not guaranteed to be current at the moment of key-press, and because the simpler center-math fix proves sufficient on the instrumented evidence.
- Alternative considered: measure container offset once per loaded video and subtract it from every seek. Rejected as over-engineering; the center-math margin absorbs every realistic offset.

### Decision 2: Do not modify `frame_to_position_ms` or `position_to_frame`

Those helpers are used by detection storage (where we want the leading-edge ms so the dict key round-trips via `int`), slider conversion (same), and the export pipeline's frame iteration. Changing them to center semantics would force every consumer to update. Instead, the center math lives only in the one place it's needed: the frame-step path.

### Decision 3: Defensively pin Qt's multimedia backend to FFmpeg

Qt6 supports at least two multimedia backends on Windows: Media Foundation (WMF) and FFmpeg. The user's current install happens to default to FFmpeg (confirmed by the `qt.multimedia.ffmpeg: Using Qt multimedia with FFmpeg version 7.1.3` log on launch). The center-math fix works on FFmpeg. It does *not* work on WMF, which refuses to re-decode on paused `setPosition()` regardless of the target ms. Setting `QT_MEDIA_BACKEND=ffmpeg` via `os.environ.setdefault` before any Qt multimedia import makes the backend explicit rather than implicit. If a future build ships with only WMF available, startup will fail loudly instead of silently regressing frame-step accuracy.

- Alternative considered: remove the env var since it's currently a no-op. Rejected because "currently a no-op" is not durable; Qt's default backend has changed between minor versions, and the app's correctness depends on FFmpeg.

## Risks / Trade-offs

- **[Risk]** A container with presentation offset >21 ms would still hit the original boundary bug. → **Mitigation:** Instrumentation showed 8 ms offset on the one affected source; H.264/HEVC typically sits well below 20 ms; defer handling until such a source is encountered.

- **[Risk]** `int((N + 0.5) * 1000.0 / fps)` for very high fps (e.g. 240) yields tiny ms steps where `int` truncation may round two adjacent frames to the same ms. → **Mitigation:** At 240 fps, step is ~4.17 ms, center-of-window is 2.08 ms inside the frame — still well above 1 ms resolution. No observed collisions.

- **[Trade-off]** The center target is slightly further from frame boundaries than the old boundary target, meaning the player lands slightly deeper inside each frame on step. User-visible effect is a barely-perceptible different "feel" of paused frame positions, but the displayed frame is still correct. Net win: correctness.

- **[Risk]** The existing `frame-precise-navigation` spec contains scenarios pinning specific ms values (e.g. "34 ms for frame 1 at 29.97 fps"). Those now change. → **Mitigation:** Spec delta rewrites those scenarios with the center-formula values.

## Migration Plan

No data migration. The change is purely a compute-the-right-number-for-setPosition fix.

**Rollout:** single commit that (a) adds `_frame_center_ms` and updates `_step_forward`/`_step_back`, and (b) pins `QT_MEDIA_BACKEND`. The diagnostic instrumentation used during investigation has been reverted; it is not part of this change.

**Rollback:** revert the two commits. No persisted state to un-migrate.

## Open Questions

- Does the user's "exported video shows all automatic plates displaced" complaint still reproduce after this fix? The preview they were using to judge correctness was itself buggy; it's plausible the export was always correct and only *appeared* wrong relative to a wrong preview. Re-verify with a fresh export before treating export as a separate bug. If it does still reproduce, open a new change to investigate — this one is scoped to the preview/stepping path.
