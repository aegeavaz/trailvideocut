## Why

Source footage frequently contains long stretches the user already knows should not appear in the final edit — the rider mounting up before moving, stops at traffic lights, pulling into a gas station, crashed-GoPro dead air. Today those frames compete with good footage during clip selection, sometimes winning coverage-zone slots or greedy-fill picks and forcing the user to rebuild marks, shuffle must-include timestamps, or re-run the pipeline to dislodge them. A direct "do not consider this time range" primitive is missing, and must-include marks are the wrong tool — they can only add, not remove.

## What Changes

- Add a temporal **exclusion range** primitive: an ordered list of `[start, end]` spans in the source video timeline that the clip selector must ignore.
- Add a new **Excluded** sub-tab on the Setup page, next to the existing Marks tab, for adding/editing/deleting ranges (start-mark/end-mark keyboard shortcut, a chip list with remove buttons, and visual indication on the video player scrubber).
- Persist ranges to a `{video_stem}.exclusions.json` sidecar. Unlike the existing `.marks.json` (which requires manual Load), this sidecar **auto-loads** when the video opens.
- Plumb ranges through `TrailVideoCutConfig.excluded_ranges` into the pipeline; filter `VideoSegment`s before coverage-zone and greedy-fill selection in `editor/selector.py`.
- Validate ranges in `pipeline._validate_inputs()`: each `start < end`, both within `[0, video_duration]`, must-include timestamps must not fall inside any excluded range.
- Expose a CLI flag (`-x / --exclude START:END`, repeatable) for scripted runs, mirroring the `-i / --include` ergonomics.

## Capabilities

### New Capabilities
- `source-exclusion-ranges`: temporal ranges of the source video that are excluded from clip selection. Covers the data model, sidecar persistence, Setup-page editor UI, pipeline/selector integration, validation rules, and CLI plumbing.

### Modified Capabilities
<!-- None. Clip selection, must-include marks, and analyzer behavior are extended by, not redefined by, this change — the new capability owns its own requirements and hooks in at a well-defined filter point. -->

## Impact

- **New code**: `src/trailvideocut/video/exclusions.py` (dataclass + sidecar I/O), `src/trailvideocut/ui/exclusions_tab.py` (Setup sub-tab widget).
- **Modified code**:
  - `src/trailvideocut/config.py` — add `excluded_ranges: list[tuple[float, float]]` field.
  - `src/trailvideocut/cli.py` — add `-x/--exclude` option with `START:END` parser.
  - `src/trailvideocut/pipeline.py` — validation in `_validate_inputs`; pass ranges to selector.
  - `src/trailvideocut/editor/selector.py` — filter segments whose midpoint falls in any excluded range, before coverage-zone selection.
  - `src/trailvideocut/ui/setup_page.py` — embed new sub-tab; wire save/load; connect to video player scrubber; emit ranges in `analyze_requested`.
  - `src/trailvideocut/ui/video_player.py` or `ui/timeline.py` — render excluded ranges as shaded spans on the scrubber.
- **APIs**: New public function `video.exclusions.load_exclusions(video_path) -> list[ExclusionRange]` and matching `save_exclusions`. Existing `CutPlan`/`EditDecision`/`VideoSegment` unchanged.
- **Dependencies**: None added — JSON sidecar uses stdlib, UI reuses existing PySide6 widgets.
- **Docs**: README "Features" list gains one bullet; CLI help string updated.
- **Backwards compatibility**: Fully additive. Absent sidecar → empty list → identical behavior to today. Existing `.marks.json` / `.plates.json` untouched.
- **Out of scope**: spatial (frame-region) exclusions; live preview of re-selection on the Review page (user re-runs analysis after editing ranges).
