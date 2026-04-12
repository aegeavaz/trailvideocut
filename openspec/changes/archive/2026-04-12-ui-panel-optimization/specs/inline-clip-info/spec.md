## ADDED Requirements

### Requirement: Display selected clip info in the summary bar
The system SHALL display the selected clip's information inline in the summary bar label at the top of the ReviewPage, appended after the existing summary stats (Tempo, Beats, Clips, CV, Duration) separated by a pipe delimiter. The clip info SHALL include: clip index, interest score, section label with energy, source time range, and target time range. When plate data exists for the clip, plate count SHALL also be shown.

#### Scenario: Clip selected on timeline
- **WHEN** the user clicks a clip on the timeline
- **THEN** the summary bar SHALL update to show the clip info appended after the base stats, e.g. `Tempo: 120 BPM | Beats: 48 | Clips: 12 | CV: 0.123 | Duration: 30.0s  |  Clip 3/12  Score: 0.456  Section: chorus (0.80)  Src: 1.20-2.40s  Tgt: 3.50-4.70s`

#### Scenario: No clip selected
- **WHEN** no clip is selected (user deselects or initial state)
- **THEN** the summary bar SHALL display only the base stats without any clip info

#### Scenario: Clip with plate data selected
- **WHEN** the user selects a clip that has plate detection data
- **THEN** the summary bar SHALL include plate info after the section label, e.g. `Plates: 15 in 8f (2m)`

### Requirement: Remove the Selected Clip panel
The system SHALL NOT display a dedicated "Selected Clip" group box panel. The `_clip_info` label and the prev/next clip navigation buttons (`_btn_prev_clip`, `_btn_next_clip`) SHALL be removed from the UI.

#### Scenario: Review page layout
- **WHEN** the ReviewPage is displayed
- **THEN** there SHALL be no "Selected Clip" group box in the bottom section

#### Scenario: Keyboard/mouse clip navigation
- **WHEN** the user wants to navigate between clips
- **THEN** the user SHALL click directly on the timeline to select clips (no dedicated prev/next buttons exist)

### Requirement: Fix preview mode clip selection positioning
The system SHALL position the video at the beginning of the selected clip (`clip.source_start`) when a clip is clicked on the timeline during preview mode. The system SHALL NOT momentarily seek to the end of the previous clip.

#### Scenario: Click clip during preview mode
- **WHEN** preview mode is active and the user clicks clip N on the timeline
- **THEN** the video SHALL seek to `clip_N.source_start` and the music player SHALL seek to `clip_N.target_start`

#### Scenario: Click first clip during preview mode
- **WHEN** preview mode is active and the user clicks the first clip on the timeline
- **THEN** the video SHALL seek to the first clip's `source_start` and the music SHALL seek to position 0 (or the first clip's `target_start`)

#### Scenario: Rapid clip switching in preview mode
- **WHEN** the user rapidly clicks multiple different clips on the timeline during preview mode
- **THEN** the video SHALL settle on the source_start of the last clicked clip without intermediate flickering to wrong positions
