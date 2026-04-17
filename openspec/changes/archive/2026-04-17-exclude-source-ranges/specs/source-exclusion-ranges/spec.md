## ADDED Requirements

### Requirement: Exclusion range data model

The system SHALL represent each exclusion as a `[start, end]` pair of floats denominated in seconds of the source video timeline, with `start < end` and both endpoints in the closed interval `[0, video_duration]`. The system SHALL maintain exclusion ranges as an ordered list sorted by `start` ascending.

#### Scenario: Valid range accepted

- **WHEN** the user or a loader provides a range where `0 <= start < end <= video_duration`
- **THEN** the system SHALL store the range and include it in the active exclusion list

#### Scenario: Inverted range rejected

- **WHEN** a range is supplied with `start >= end`
- **THEN** the system SHALL reject the range with an error identifying both endpoints, and SHALL NOT add it to the list

#### Scenario: Out-of-duration range rejected

- **WHEN** a range has `start < 0` or `end > video_duration`
- **THEN** the system SHALL reject the range with an error identifying the offending endpoint and the video's duration

### Requirement: Overlap prevention

The system SHALL reject any exclusion list in which two ranges overlap. Two ranges `[a, b]` and `[c, d]` overlap iff `a < d AND c < b`. Adjacency (touching endpoints, e.g., `b == c`) is NOT overlap.

#### Scenario: Overlapping ranges rejected at pipeline validation

- **WHEN** `pipeline._validate_inputs` receives two exclusion ranges that overlap
- **THEN** the system SHALL raise a validation error identifying both colliding ranges and SHALL NOT start analysis

#### Scenario: Touching endpoints accepted

- **WHEN** two exclusion ranges share an endpoint (`[10, 20]` and `[20, 30]`)
- **THEN** the system SHALL accept both ranges as non-overlapping

### Requirement: Must-include mark collision rejected

The system SHALL reject any configuration in which a must-include timestamp (`config.include_timestamps`) falls strictly inside any exclusion range `(start, end)`.

#### Scenario: Include mark inside exclusion rejected

- **WHEN** `config.include_timestamps` contains a timestamp `t` and an exclusion range `[start, end]` exists with `start < t < end`
- **THEN** the system SHALL raise a validation error identifying the timestamp and the colliding range, and SHALL NOT start analysis

#### Scenario: Include mark on exclusion boundary accepted

- **WHEN** a must-include timestamp equals the `start` or `end` of an exclusion range
- **THEN** the system SHALL accept the configuration (boundary timestamps are not strictly inside)

### Requirement: Segment filtering before clip selection

The system SHALL filter `VideoSegment`s before include-segment reservation, coverage-zone selection, and greedy fill in `SegmentSelector.select()`. A segment is excluded iff its midpoint (`(start + end) / 2`) falls strictly inside any exclusion range.

#### Scenario: Segment midpoint inside exclusion is filtered

- **WHEN** a `VideoSegment` has midpoint `m` and an exclusion range `[s, e]` exists with `s < m < e`
- **THEN** the selector SHALL remove the segment from its candidate pool and SHALL NOT assign it to any coverage zone or greedy-fill slot

#### Scenario: Segment midpoint on exclusion boundary is retained

- **WHEN** a `VideoSegment` has a midpoint equal to the `start` or `end` of an exclusion range
- **THEN** the selector SHALL retain the segment as a candidate

#### Scenario: No exclusions yields baseline behaviour

- **WHEN** `config.excluded_ranges` is empty
- **THEN** `SegmentSelector.select()` SHALL produce an identical `CutPlan` to a run with no exclusions defined, byte-for-byte on EditDecision fields for a fixed seed

### Requirement: Undercount and empty-result handling

The system SHALL NOT fail clip selection solely because exclusions reduce the candidate pool below the target clip count; it SHALL use the existing undercount fallback path and emit a warning that names the shortfall. The system SHALL raise an error if, after exclusion, the candidate pool is empty.

#### Scenario: Undercount after exclusion

- **WHEN** after exclusion filtering fewer candidate segments remain than the target clip count, but at least one remains
- **THEN** the system SHALL complete selection using the remaining candidates and SHALL emit a warning stating the requested count, the produced count, and the total excluded duration in seconds

#### Scenario: Empty candidate pool after exclusion

- **WHEN** after exclusion filtering zero candidate segments remain
- **THEN** the system SHALL raise an error whose message names exclusions as the cause and references the user's exclusion-list editing point

### Requirement: Sidecar persistence and auto-load

The system SHALL persist exclusion ranges to a sidecar JSON file named `{video_stem}.exclusions.json` in the same directory as the source video. The file SHALL include a `version` integer, a `video_filename` string, and a `ranges` array of `{"start": float, "end": float}` objects. The system SHALL auto-load the sidecar when the video is opened.

#### Scenario: Sidecar saved on edit

- **WHEN** the user adds, deletes, or modifies an exclusion range in the GUI
- **THEN** the system SHALL write the full ordered list to `{stem}.exclusions.json`, creating the file if missing or overwriting if present

#### Scenario: Sidecar auto-loaded on video open

- **WHEN** the user opens a video in the Setup page and a matching `.exclusions.json` exists
- **THEN** the system SHALL deserialize the ranges, validate them against the video duration, and populate the in-memory exclusion list without requiring a manual Load action

#### Scenario: Sidecar missing on video open

- **WHEN** the user opens a video with no matching sidecar
- **THEN** the system SHALL initialize an empty exclusion list and produce no warning

#### Scenario: Sidecar with mismatched filename

- **WHEN** the loaded sidecar's `video_filename` field does not match the currently opened video's filename
- **THEN** the system SHALL discard the sidecar contents, display a warning stating the mismatch, and start with an empty exclusion list

#### Scenario: Sidecar with unknown version

- **WHEN** the loaded sidecar's `version` field does not match any version the code knows how to read
- **THEN** the system SHALL discard the sidecar contents, display a warning identifying the version seen vs. expected, and start with an empty exclusion list

#### Scenario: Sidecar corrupt or unparseable

- **WHEN** the sidecar file cannot be parsed as JSON or fails schema validation
- **THEN** the system SHALL discard the contents, display a warning, start with an empty exclusion list, and preserve the offending file on disk unchanged

#### Scenario: Write permission denied

- **WHEN** the system attempts to save a sidecar update but the target directory is read-only
- **THEN** the system SHALL display a warning naming the path and continue with in-memory state only

### Requirement: Setup-page exclusion editor

The system SHALL provide an **Excluded** sub-tab on the Setup page, adjacent to the existing **Marks** sub-tab, for editing exclusion ranges interactively. The editor SHALL support creating a range via two actions (start at current player position, end at current player position), deleting any existing range, clearing all ranges with confirmation, and viewing ranges as a chronologically ordered list of chips.

#### Scenario: Create range using Start and End actions

- **WHEN** the user triggers "Start" at player position `t1`, scrubs to `t2 > t1`, and triggers "End"
- **THEN** the system SHALL add `[t1, t2]` to the exclusion list, insert it in sorted order, and persist the updated list to the sidecar

#### Scenario: Cancel a pending start

- **WHEN** the user has triggered "Start" at `t1` but has not yet triggered "End", and the user triggers the cancel action
- **THEN** the system SHALL discard the pending start, add nothing to the list, and leave persisted state unchanged

#### Scenario: End before Start rejected

- **WHEN** the user triggers "End" at a player position less than or equal to the pending "Start" position
- **THEN** the system SHALL display an inline error, discard the pending start, and add nothing to the list

#### Scenario: Delete a single range from the chip list

- **WHEN** the user clicks the remove button on a chip representing range `r`
- **THEN** the system SHALL remove `r` from the exclusion list and persist the updated list to the sidecar

#### Scenario: Clear all ranges

- **WHEN** the user triggers "Clear All" and confirms the prompt
- **THEN** the system SHALL empty the exclusion list and persist the empty list to the sidecar

### Requirement: Scrubber visualization of excluded ranges

The system SHALL render each active exclusion range as a shaded span on the Setup-page video scrubber, visually distinct from must-include marks and from the scrubber's own progress fill.

#### Scenario: Ranges visible on scrubber

- **WHEN** one or more exclusion ranges are present in the editor
- **THEN** the video scrubber SHALL render each as a shaded span spanning the pixel interval corresponding to `[start, end]` of the range

#### Scenario: Scrubber updates on edit

- **WHEN** the user adds, removes, or modifies a range
- **THEN** the scrubber overlay SHALL repaint within the same UI tick to reflect the updated exclusion list

### Requirement: CLI exclusion flag

The system SHALL accept a `--exclude` (short `-x`) option on the `cut` command that is repeatable and takes a value formatted as `START:END` where `START` and `END` are non-negative floats in seconds separated by a single colon. The flag SHALL populate `config.excluded_ranges`.

#### Scenario: Single exclusion on CLI

- **WHEN** the user runs `trailvideocut cut ride.mp4 song.mp3 -x 0:30`
- **THEN** the system SHALL populate `config.excluded_ranges` with `[(0.0, 30.0)]` and apply it during selection

#### Scenario: Multiple exclusions on CLI

- **WHEN** the user supplies `-x 0:30 -x 120.5:145` in the same invocation
- **THEN** the system SHALL populate `config.excluded_ranges` with both tuples, sorted by start

#### Scenario: Malformed exclusion value

- **WHEN** the user supplies `-x` with a value that cannot be parsed as `float:float` (e.g., `-x 30`, `-x abc:10`, `-x 1:2:3`)
- **THEN** the CLI SHALL exit non-zero with an error naming the offending value and the expected `START:END` format, before any pipeline work starts
