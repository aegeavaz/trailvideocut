## 1. Data model & persistence

- [x] 1.1 Create `src/trailvideocut/video/exclusions.py` with an `ExclusionRange` dataclass (`start: float`, `end: float`) including post-init validation for `start < end`.
- [x] 1.2 Add helper `overlaps(a: ExclusionRange, b: ExclusionRange) -> bool` using the strict `a.start < b.end and b.start < a.end` rule.
- [x] 1.3 Add helper `contains(ranges: list[ExclusionRange], t: float) -> bool` using strict-inside semantics (`start < t < end`).
- [x] 1.4 Add helper `validate_exclusions(ranges, video_duration, include_timestamps) -> None` that raises `ValueError` on inverted, out-of-duration, overlapping, or include-colliding inputs — with messages naming offending values.
- [x] 1.5 Write `tests/test_video_exclusions.py` covering every validation rule and both `overlaps` / `contains` boundary cases. Pure unit tests, no I/O.
- [x] 1.6 In the same module add `get_exclusions_path(video_path)`, `save_exclusions(video_path, ranges)`, `load_exclusions(video_path) -> list[ExclusionRange]`, `delete_exclusions(video_path)`, mirroring `plate/storage.py` shape. Sidecar schema: `{"version": 1, "video_filename": str, "ranges": [{"start": float, "end": float}, ...]}`.
- [x] 1.7 Extend `load_exclusions` with the mismatched-filename, unknown-version, and unparseable-JSON paths — each returns empty list + logs warning, does NOT raise.
- [x] 1.8 Write `tests/test_video_exclusions_storage.py` covering round-trip save/load, missing sidecar, version mismatch, filename mismatch, corrupt file, and write-permission-denied (using a read-only tmp dir).

## 2. Config & pipeline plumbing

- [x] 2.1 Add `excluded_ranges: list[tuple[float, float]] = field(default_factory=list)` to `TrailVideoCutConfig` in `src/trailvideocut/config.py`.
- [x] 2.2 In `pipeline._validate_inputs`, call `video.exclusions.validate_exclusions(...)` against the resolved video duration and `config.include_timestamps`. Add a test in `tests/test_pipeline.py` (or nearest existing) that this raises for each of the four validation failure modes.
- [x] 2.3 Propagate `config.excluded_ranges` into `SegmentSelector` construction (plumb through `pipeline.py` at the point where the selector is built — same spot that reads `include_timestamps` today).

## 3. Selector integration

- [x] 3.1 In `editor/selector.py`, add a private `_filter_excluded(segments)` method that drops any `VideoSegment` whose midpoint is strictly inside any exclusion range.
- [x] 3.2 Call `_filter_excluded` at the top of `SegmentSelector.select()`, *before* include-segment reservation, coverage-zone computation, and greedy fill.
- [x] 3.3 In the empty-pool branch, raise a clear `RuntimeError` whose message names exclusions as the cause and the exclusion count.
- [x] 3.4 Extend the undercount path (selector.py:195-211) to include in its warning the requested-vs-produced counts and the total excluded duration computed from `config.excluded_ranges`.
- [x] 3.5 Add `tests/test_selector_exclusions.py`:
  - [x] 3.5.1 Baseline: empty `excluded_ranges` → byte-identical `CutPlan` to today (golden-fixture test; capture the fixture in this same commit).
  - [x] 3.5.2 Single exclusion covering a known coverage zone → that zone picks from outside the range; `CutPlan.decisions` count unchanged.
  - [x] 3.5.3 Segment midpoint exactly on exclusion boundary → segment retained.
  - [x] 3.5.4 Exclusions leaving fewer candidates than target → undercount path taken; warning emitted and captured via `caplog`.
  - [x] 3.5.5 Exclusions filtering every candidate → `RuntimeError` raised with exclusions named in the message.
- [x] 3.6 Run the existing selector test suite to confirm no regressions with exclusions disabled.

## 4. CLI

- [x] 4.1 In `src/trailvideocut/cli.py`, add `-x / --exclude` option with `multiple=True`, help text "`START:END` time range in seconds to exclude from clip selection; repeatable".
- [x] 4.2 Add a private `_parse_exclusion(value: str) -> tuple[float, float]` helper. Exactly one `:`, both sides parse as non-negative floats, `start < end`. Raise `typer.BadParameter` with the raw offending value on any failure.
- [x] 4.3 Populate `config.excluded_ranges` from parsed values, sorted by start.
- [x] 4.4 Extend `tests/test_cli.py` (or create) with: single `-x`, multiple `-x`, malformed value (`30`, `abc:10`, `1:2:3`), negative value, inverted (`30:10`) — each asserting exit code and stderr content.

## 5. UI — Excluded sub-tab

- [x] 5.1 Create `src/trailvideocut/ui/exclusions_tab.py` exposing `ExclusionsTab(QWidget)` with signals `ranges_changed(list[tuple[float, float]])` and a public `set_ranges(...)` / `set_player_position(...)` API.
- [x] 5.2 Implement the chip-list widget: sorted by start, each chip shows `HH:MM:SS.ss → HH:MM:SS.ss` and carries a remove button emitting `ranges_changed`.
- [x] 5.3 Implement Start / End buttons with `I` (in-point) / `O` (out-point) keyboard shortcuts and `Esc` to cancel a pending Start. End-before-Start surfaces an inline status message; no exception.
- [x] 5.4 Implement "Clear All" with a confirmation dialog.
- [x] 5.5 In `src/trailvideocut/ui/setup_page.py`, instantiate `ExclusionsTab` and insert it into the existing sub-tab widget adjacent to the Marks tab. Wire `ranges_changed` into a handler that (a) persists to sidecar via `save_exclusions`, (b) updates the scrubber overlay, (c) stores the latest list for emission in `analyze_requested`.
- [x] 5.6 On video open: call `load_exclusions(video_path)` and seed `ExclusionsTab.set_ranges(...)`. Surface any warning path from load as a non-blocking status message.
- [x] 5.7 Extend `analyze_requested` payload to include `excluded_ranges`; update the signal signature and all receivers (main window / workers).

## 6. UI — Scrubber overlay

- [x] 6.1 In `src/trailvideocut/ui/video_player.py` (or `timeline.py` if the Setup player shares it), add `set_excluded_ranges(ranges)` that stores the list and calls `update()`.
- [x] 6.2 Extend the scrubber's `paintEvent` to draw each range as a semi-transparent red span bounded by the pixel columns mapped from `[start, end]`. Ensure it renders beneath the must-include mark lines (marks should remain visible on top).
- [x] 6.3 Add an interactive smoke test or screenshot-diff (whatever the project already uses for UI) confirming shaded-span rendering for one, multiple, and zero ranges.

## 7. End-to-end verification

- [x] 7.1 Manual: open a sample ride video in Setup, create two exclusion ranges, close app, reopen — confirm ranges auto-load and show on scrubber.
- [x] 7.2 Manual: run `trailvideocut cut sample.mp4 song.mp3 -x 0:30 -o out.mp4` and confirm (a) no clips start before 30s in any `EditDecision`, (b) console logs a summary line mentioning the exclusion.
- [x] 7.3 Manual: create an include mark inside an exclusion range — confirm validation error names both colliding values and analysis does not start.
- [x] 7.4 Manual: exclude ~95% of a short sample and confirm the "empty after exclusion" error fires with a helpful message (not a traceback dump).
- [x] 7.5 Run the full test suite (`pytest`) and `ruff check` — zero new failures or warnings.

## 8. Documentation

- [x] 8.1 Add a "Exclusion ranges" bullet to the README Features list and a one-paragraph usage example under Usage → CLI.
- [x] 8.2 Mention the sub-tab in the README Usage → GUI section (one sentence).
- [x] 8.3 Update the CLI `cut` command help text so `trailvideocut cut --help` shows `-x/--exclude` with a concrete example.
