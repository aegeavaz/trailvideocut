## Context

TrailVideoCut analyses source footage (`video/analyzer.py`) into overlapping `VideoSegment` objects, each scored by optical flow, color change, edge variance, and brightness change (`video/models.py`). `editor/selector.py::SegmentSelector.select()` then (a) reserves segments overlapping user-supplied must-include timestamps, (b) fills coverage zones with the best-scoring segment in each zone, and (c) greedily picks remaining slots with spacing/cluster limits. The final `CutPlan` is rendered or exported.

Two primitives already steer selection, and they bound the design space for the new one:

1. **Must-include marks** (`config.include_timestamps`, CLI `-i`, Setup-page Marks tab). Sidecar: `{stem}.marks.json`. Manual Load.
2. **Plate regions** (`plate/`, `.plates.json`). Sidecar auto-loads on Review. Structured JSON with `version` field and filename validation.

Today there is no way for the user to say "do not pick from this time range." Workarounds — flooding the area with must-include marks pointing to adjacent good moments, trimming the source offline, or chipping away at `CutPlan` clips on the Review page — are all worse than adding the primitive directly. The feature is additive, affects one well-defined filter point in `SegmentSelector`, and has a natural sidecar pattern to copy from plates.

Stakeholders: single-user desktop app (CLI + GUI). No server, no migrations.

## Goals / Non-Goals

**Goals:**
- Let the user define an ordered list of `[start, end]` time ranges in the source video that `SegmentSelector` must ignore. Effect is a hard exclusion — no coverage-zone pick, no greedy fill, no fallback pick.
- GUI: editable list on the Setup page, co-located with must-include marks, with shaded overlay on the video scrubber so users see what they've excluded at a glance.
- CLI: `-x START:END` flag (repeatable) matching `-i` ergonomics.
- Persistence: auto-load `{stem}.exclusions.json` on video open; save on every edit. Survives app restart with no manual action.
- Validation: reject overlapping ranges, out-of-duration ranges, and must-include timestamps that fall inside an excluded range — fail loudly before analysis runs, not silently during selection.
- Behavior when the user's edit has removed all usable footage → clear error. No mystery empty `CutPlan`.

**Non-Goals:**
- Spatial (frame-region) exclusions. Out of scope; the plate feature already carves that territory.
- Soft penalties or score dampening. Exclusions are hard, not weighted — if a user wants a region "down-weighted but eligible," they should leave it out of the list and use must-include marks on the good parts elsewhere.
- Re-selection on the Review page in response to edits. User re-runs analysis after editing ranges (same flow as editing must-include marks today).
- Merging with or replacing `.marks.json`. Different primitive, different file.
- Migrating existing users — there is no prior exclusion state to migrate.

## Decisions

### D1: Hard exclusion in `SegmentSelector`, not in the analyzer

**Decision:** Filter `VideoSegment`s in `editor/selector.py::SegmentSelector.select()` *before* include-segment reservation, coverage-zone selection, and greedy fill. The analyzer produces the full segment list as today.

**Rationale:** The analyzer's output is cache-friendly and frequently re-used across different selections (different include lists, different beat plans). Filtering downstream keeps the cached analysis valid when the user tweaks ranges and only touches a cheap post-processing step. It also keeps the exclusion primitive purely about selection, not about scoring, which matches the mental model.

**Alternatives considered:**
- *Filter at the analyzer, skip the frames entirely.* Rejected: throws away cacheable work; if the user removes a range they have to re-analyze.
- *Zero-score segments in excluded ranges.* Rejected: coverage-zone code picks "best in zone" — a zero-scored segment can still win an empty zone, producing dead air in the final cut.

**Overlap rule:** A segment is excluded iff its `midpoint` falls inside any excluded range. Using midpoint avoids boundary ambiguity for segments that straddle a range edge and keeps filter logic to one comparison per segment. `SegmentSelector` already uses midpoint-style tests elsewhere in clustering/spacing, so this is consistent.

### D2: Validation is an error, not a warning

**Decision:** `pipeline._validate_inputs` raises on (a) any `start >= end`, (b) any range outside `[0, video_duration]`, (c) any pair of overlapping ranges, (d) any must-include timestamp inside any excluded range.

**Rationale:** All four states indicate the user's intent is incoherent, and silently ignoring them produces results that are hard to debug. Fail-fast at the boundary is cheap and obvious. The must-include-vs-exclude check is the subtlest — without it, the user can pin a timestamp that the selector can never land on, and they'll get a confusing "clip not found" scenario deep in `_resolve_include_segments`.

**Alternatives considered:**
- *Auto-merge overlapping ranges and continue.* Rejected: users who entered overlapping ranges probably mistyped — correcting their input silently hides the mistake.
- *Drop must-include marks that collide, warn.* Considered. Rejected for v1 because "quietly drop your pins" is worse than "tell you what's wrong." Can be revisited if real-world usage shows it's annoying.

### D3: Sidecar auto-loads, mirrors plate pattern (not marks pattern)

**Decision:** `{video_stem}.exclusions.json` auto-loads when the video is opened in Setup. Schema:

```json
{
  "version": 1,
  "video_filename": "ride.mp4",
  "ranges": [{"start": 12.34, "end": 45.67}, ...]
}
```

Save on every edit (add / remove / modify). On load, validate version and filename; on mismatch, discard + warning banner, keep empty list.

**Rationale:**
- Auto-load matches user expectation for "state I committed to this video" and matches the plate sidecar, which is the more modern pattern. Manual-Load `.marks.json` predates the plate work and is inconsistent; we are not obligated to repeat the mistake.
- Versioning and filename check give us room to evolve the schema without surprising users with garbled state from an old file.
- Saving on every edit is cheap (small JSON) and removes a "forgot to save" failure mode.

**Alternatives considered:**
- *Share `.marks.json` with must-include.* Rejected: the sentinel-value approach (e.g., negative-end for exclusion) obscures the semantics and couples two independent features in one file.
- *Single unified project file for the video.* Tempting long-term but out of scope here; it would subsume `.marks.json`, `.plates.json`, and `.exclusions.json` and is a bigger architectural decision than this change should make. Noted as open question.

### D4: CLI `-x START:END` with colon separator

**Decision:** `-x / --exclude START:END` on the `cut` command, `multiple=True`. Parser splits on the first `:`, treats both halves as `float`, constructs a `tuple[float, float]`, passes to `config.excluded_ranges`.

**Rationale:** `-i` uses bare floats because its primitive is a single timestamp. A range needs two. Colon is unambiguous in `float:float`, keeps the flag one-token-per-value, and is easy to repeat (`-x 0:30 -x 120:135`). Follows standard "from:to" conventions used in ffmpeg's `-ss`/`-to` style arguments that this tool's users are already familiar with.

**Alternatives considered:**
- *Two flags `--exclude-start` / `--exclude-end`.* Rejected: can't be repeated coherently, error-prone pairing.
- *Config-file-only (no CLI).* Rejected: breaks parity with `-i` and makes scripting awkward.

### D5: UI — Excluded sub-tab on Setup, with scrubber overlay

**Decision:** Add an **Excluded** sub-tab on the Setup page adjacent to the existing **Marks** sub-tab. Contents:

- Video player above (shared with Marks tab, unchanged).
- Two-button row: **Start** (sets pending start to player position) and **End** (commits range from pending start to player position). Keyboard shortcuts: `I` = Start (in-point), `O` = End (out-point). `Esc` cancels the pending start. Mirrors NLE convention (Premiere / DaVinci Resolve / FFmpeg `-ss`/`-to` semantics) so users with editing background have zero-cost muscle memory.
- Chip list below: `[00:12.34 → 00:45.67] [×]` rows, scrollable, sorted by start time.
- "Clear All" button with confirmation.
- Shaded span rendering on the video player scrubber via `video_player.set_excluded_ranges(...)` or a new `timeline.py` hook — red-tinted semi-transparent overlay so the user sees exclusions in the same visual channel as marks (which are lines).

**Rationale:**
- Sub-tab, not new page: keeps the Setup → Review → Export wizard flow intact. User already tabs between Marks and Settings; adding a third tab costs nothing.
- Start/End buttons instead of direct range dragging: drag-to-select on a scrubber is nice but meaningfully harder to build reliably, and this first cut needs to be tight. Revisit for v2 if users ask.
- Scrubber overlay is non-negotiable — without visual feedback the user can't tell exclusions from marks from Review clips.

**Alternatives considered:**
- *New Review-page editor with live re-selection.* Rejected (non-goal): too much re-analysis plumbing for v1.
- *Drag-to-select on scrubber as the only editor.* Deferred to a possible follow-up.

### D6: Selector degrades gracefully when exclusions leave too little footage

**Decision:** If the filtered segment list after exclusion is smaller than the requested target clip count, `SegmentSelector` falls back to its existing "undercount" path (selector.py:195-211) and returns whatever clips it can. `pipeline.py` emits a clear warning including how many clips were requested vs. produced and the total excluded duration. If the filtered list is *empty*, `pipeline` raises with a message pointing the user at their exclusion edits.

**Rationale:** The existing undercount path is already load-bearing for very short source videos; we lean on it rather than duplicating the logic. Empty-after-exclusion is an error, not a warning, because the output would be an empty `CutPlan` — nothing useful to render.

## Risks / Trade-offs

- **User excludes too much, cut comes up short** → Selector undercount path already exists; log a clear warning with excluded-duration totals so the user knows it was their edit, not a bug.
- **Midpoint overlap rule misses partial exclusions** (a segment whose midpoint is outside the range but tail sticks into it still gets picked; `_align_segment` will then pull a few frames from inside the excluded span) → For v1, accepted: segment windows are short and `_align_segment` centers extraction, so leakage is minimal. If users report it, upgrade the rule to "any overlap" and re-evaluate — add a test that pins the behavior so the regression is visible.
- **Auto-save-on-edit causes writes during rapid keyboard edits** → JSON is small; debounce to the next idle tick via `QTimer.singleShot(0, ...)` if measured to matter. Out-of-the-box unoptimized write is still well under 1 ms on typical range counts.
- **Sidecar schema drift** → `version` field + filename check + discard-and-warn path gives us a controlled migration surface. Plate feature already exercises this pattern.
- **CLI parser ambiguity with negative floats** (`-x -1:5` looks like a flag) → Enforce non-negative starts in validation; unlikely real concern, document the canonical form (`-x 1.5:5`).
- **Must-include + exclusion collision surprises user** → Validation error at pipeline entry names both colliding timestamps so the user can fix one or the other.
- **Drag-to-select deferred** → users may request it. Acceptable — feature ships first, enhancement later.

## Migration Plan

- Additive. No existing user state to migrate. Missing sidecar = empty list = today's behavior.
- Rollback: delete the new UI tab + selector filter call + config field + CLI flag. `.exclusions.json` files left on disk are harmless; would simply be ignored.
- No data migration tooling needed.

## Open Questions

- Should `.marks.json`, `.plates.json`, and `.exclusions.json` eventually consolidate into one `{stem}.trailvideocut.json` project file? Out of scope here but worth capturing — affects any future third feature that wants per-video state.
- Are there existing `SegmentSelector` tests that assert the coverage-zone output for a known input? If so the exclusion tests should extend that suite; if not, we create the golden fixtures as part of this work (captured in tasks.md).
- Should the scrubber overlay colour be user-configurable? Not for v1 — reasonable default (semi-transparent red) and move on.
