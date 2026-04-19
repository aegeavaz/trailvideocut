## Context

`fix-automatic-plate-position-displacement` (archived 2026-04-18) fixed the preview-side frame-stepping math so the video surface now lands on source frame N per arrow-key step. Against that now-correct reference, the user tested an export and reports the blur box appears one frame ahead of the plate.

Two offsets currently live on the export side, both landed when the preview was still broken:

1. `src/trailvideocut/plate/blur.py:530` — `lookup_frame = abs_frame + 1`, introduced on 2026-04-15 (commit `aadce99`). The commit's narrative: "OpenCV's `cap.set()` lands mid-GOP for most segments, so OpenCV returns source frame (abs_frame+1) content for the entire segment — it never resyncs because the segment typically ends before the decoder catches up." That narrative was validated by eye against the then-broken preview.
2. `src/trailvideocut/editor/resolve_script.py:209` — `comp_for_rel(rel) = clip_offset + rel + pts_gap_offset`, where `pts_gap_offset = -1` if `PTS_GAP_KEYFRAME ~= nil` (commit `abf88d5`). Also validated against the old preview, but only active on clips that cross a PTS-gap keyframe.

The detector writes `detections[frame_num] = boxes` with `frame_num` being the OpenCV source-frame index (`detector.py:676`; also `temporal_filter.py:119`, `storage.py:117`). So the intended invariant across preview, MP4 export, and DaVinci Fusion output is: **`boxes[N]` is drawn at visible source frame N, everywhere**. Any extra offset on one surface breaks cross-surface consistency.

Stakeholders: single developer (the user). No external compatibility constraints. Backwards-compat with past sidecar files is preserved — plate keys are not changing.

## Goals / Non-Goals

**Goals:**
- Restore cross-surface alignment: preview, MP4 export, and DaVinci Fusion composition all reference `boxes[N]` at source frame N, verified empirically.
- Make the MP4 export verifiable in CI via a deterministic, self-contained integration test (burned-in frame-number clip → export → decode-back assertion).
- Leave the DaVinci `pts_gap_offset` branch in place *only if* evidence supports it; otherwise remove it. Either way, the new spec records the condition explicitly.
- Add an FFmpeg-path-scoped no-offset requirement to `plate-blur-export`, without touching the live MoviePy-fallback requirement or its self-calibrating helpers.

**Non-Goals:**
- Refactoring `PlateBlurProcessor` architecture beyond the frame-key fix. The `_nearest_boxes` window, the YUV tempfile flow, and the per-segment progress callback are out of scope.
- Touching `frame-precise-navigation`. The stepping math was already fixed; this change is about export-side invariants.
- Modifying detector keys, storage format, or overlay rendering. The canonical key is already `int(abs_frame)`; this change only enforces consumers honour it.
- Providing a "detect the real OpenCV mid-GOP behaviour" runtime probe. The integration test is enough.

## Decisions

### Decision: Anchor the fix to an empirical, self-contained test rather than a code review

**Context**: The history shows two rounds of "fix the offset" based on visual inspection against a broken preview. Another eyeball-only round would be the same trap.

**Choice**: Write a pytest integration test that:
1. Generates a short H.264 clip where each frame's pixel content encodes the frame number (ffmpeg `drawtext` with `%{n}`, or a simpler OpenCV-generated clip with a small solid-colour indicator per frame).
2. Fabricates a `ClipPlateData` with a plate detection at a single known source frame K placed over a fixed region of the burn-in.
3. Runs the MP4 export path end-to-end (or `PlateBlurProcessor.process_segment` directly, depending on which level is easier to hold deterministic).
4. Decodes the exported output at frame K with OpenCV and asserts the blur-region pixels differ from the reference burn-in (blurred away) while the adjacent frame K±1 pixels remain identical to the reference.

**Alternatives considered**:
- *Unit test on `_get_boxes_for_frame` only*: catches the `+1` in isolation but cannot distinguish "correctly compensating for an OpenCV quirk" from "wrong". Only an end-to-end pixel test settles that.
- *Manual test with the user's video*: not reproducible, not regression-proof, same failure mode as before.

**Trade-off**: The test requires ffmpeg to be available (it already is — export path depends on it) and takes a second or two to generate and decode a tiny clip. Acceptable.

### Decision: Remove the `+1` in `blur.py` unconditionally, guarded by the TDD test

**Context**: The cited rationale for `+1` (mid-GOP OpenCV seek returns frame N+1 content) is a *known historical bug* in older OpenCV/FFmpeg backends that has been largely fixed in recent versions. With OpenCV 4.x on modern FFmpeg, `cap.set(CAP_PROP_POS_FRAMES, N); cap.read()` returns frame N for keyframe-aligned N, and for mid-GOP N the decoder reads up to N and returns N — not N+1. The commit introduced the `+1` to fix a visible mismatch, but that mismatch was the preview rendering the wrong frame on step, not OpenCV returning the wrong frame on seek.

**Choice**: Change `lookup_frame = abs_frame + 1` to `lookup_frame = abs_frame`. Centralise the lookup in a tiny helper `PlateBlurProcessor._lookup_key(abs_frame)` so the test has a seam and future offset temptations have one obvious place to be rejected.

**Alternatives considered**:
- *Make the offset a config knob*: defers the decision and invites regressions.
- *Keep piecewise keyframe-conditional correction (the pre-aadce99 logic)*: the original rationale for the piecewise was also unverified post-preview-fix. If the TDD test fails with direct lookup, we reconsider then.

### Decision: For DaVinci, audit but do not preemptively remove `pts_gap_offset`

**Context**: The `pts_gap_offset = -1` branch is conditional on `PTS_GAP_KEYFRAME` being set by the exporter, which is itself conditional on ffprobe detecting a PTS discontinuity. It only fires on specific clips. Unlike the MP4 `+1`, which fires unconditionally, this one may be addressing a real Resolve-side phenomenon that outlives the preview fix.

**Choice**: Keep the branch in place during this change. Task: manually verify one known-PTS-gap clip through DaVinci with `pts_gap_offset = -1` vs `0` and record the result in the PR / archive. If `0` is clearly correct, remove it in a follow-up (scope-creep hazard if bundled). The spec is written so that *either* outcome satisfies the invariant — the requirement mandates evidence, not a specific value.

**Alternatives considered**:
- *Remove it in this change*: riskier without a DaVinci-side test harness, and the user cannot verify at commit time.
- *Ignore it entirely*: leaves the export spec silent about a live offset. Rejected — that's what let it slip in the first place.

### Decision: Leave the MoviePy fallback's spec requirement intact; add a new FFmpeg-scoped requirement

**Context**: An earlier draft of this proposal treated the MoviePy path as removed, but `assembler.py:834`'s `_assemble_moviepy` is still a live fallback that invokes `calibrate_frame_offset` and `expand_boxes_for_drift` from `blur.py`. Its self-calibrating MSE search and drift-union behaviour are independent of the primary FFmpeg path and were not reported broken by the user.

**Choice**: Add a new requirement that scopes the no-offset invariant explicitly to `PlateBlurProcessor.process_segment` (the FFmpeg route). Leave the MoviePy-fallback requirement unchanged. This avoids over-tightening into territory that would ban live, working behaviour.

**Alternatives considered**:
- *Tighten the top-level `Apply Gaussian blur to detected plate regions during export` requirement with a blanket no-offset clause*: rejected — would outlaw the MoviePy fallback's calibrate+expand behaviour.
- *Mark the MoviePy fallback deprecated in this change*: out of scope; no evidence the fallback is failing and no reason to tie fallback removal to this fix.

## Risks / Trade-offs

- **Risk**: Removing `+1` breaks a different clip where OpenCV genuinely did return N+1 content for this codebase's typical inputs. → *Mitigation*: the pixel-level integration test proves alignment on at least one representative synthetic clip. If the user's real videos break, the test can be extended with a curated fixture and the offset re-introduced behind a codec/container detection condition, but only with evidence.
- **Risk**: DaVinci `pts_gap_offset` is actually wrong in the spurious direction and the manual audit misses it (the Fusion output is at the whim of Resolve's rendering). → *Mitigation*: record the audit procedure and the clip used in the archive's tasks.md so it can be rerun later.
- **Risk**: Burned-in-frame-number fixture clip is flaky across ffmpeg versions (some lack `drawtext`). → *Mitigation*: generate the clip via OpenCV `VideoWriter` writing solid-colour frames whose hue encodes the frame index — no ffmpeg filter dependency, only the libavcodec/libavformat that OpenCV already links.
- **Trade-off**: Test adds a few seconds to CI. Acceptable for a regression that cost two round-trips to diagnose.

## Migration Plan

1. Land the integration test first, passing against the synthesized clip but demonstrating the *failure* of the current `+1` code via a preliminary run (captured in the PR description).
2. Remove the `+1`; the test passes.
3. Run existing tests + `openspec validate`.
4. Manual DaVinci audit on a PTS-gap clip. Record outcome.
5. Merge. If anything regresses on real videos, revert is a one-line change (reintroduce `+ 1`), and the test fixture tells us where the new divergence is.
