## Why

Selecting a clip in the Review-page clip list sometimes displays the frame immediately *before* the clip's true start — the same off-by-one symptom that arrow-key stepping already solves. The current `VideoPlayer.seek_to(seconds)` naively computes `int(seconds * 1000)`, which targets the *leading edge* of the frame's ideal time window. For real H.264/HEVC containers whose presentation timestamps drift a few ms from the ideal `t = N/fps` model, that leading-edge target can land inside the *previous* frame's actual display window, so the decoder surface stays on the wrong frame even though the slider and frame label advance.

## What Changes

- Route `VideoPlayer.seek_to(seconds)` through the same frame-centre arithmetic already used by `_step_forward` / `_step_back`, so clip-click seeks land inside the target frame's actual presentation window for any realistic container offset.
- Use `trailvideocut.utils.frame_math.position_to_frame` to resolve the caller's seconds-valued argument to the source-frame index the decoder should land on, then drive `_seek` with `_frame_center_ms(frame)`.
- Apply the same centre-of-window guarantee to every caller of `seek_to` (clip click in Review, preview mid-clip re-seeks, mark jumps in Setup), since they all share the one helper.

## Capabilities

### New Capabilities
<!-- None. -->

### Modified Capabilities
- `frame-precise-navigation`: extends the centre-of-window seek guarantee from keyboard stepping to arbitrary seconds-valued seeks (`seek_to`), so clip-list clicks and other programmatic seeks land on the same frame the decoder displays.

## Impact

- Code: `src/trailvideocut/ui/video_player.py` (`seek_to` body) — behaviour change only, signature unchanged.
- Callers (unchanged at call sites): `review_page.py` (clip selected, preview re-seek), `setup_page.py` (mark jump).
- Tests: add regression tests against `VideoPlayer.seek_to` covering the 29.97/23.976 fps boundary cases already used by the frame-precise-navigation spec.
- No data, APIs, or persistence impacted.
