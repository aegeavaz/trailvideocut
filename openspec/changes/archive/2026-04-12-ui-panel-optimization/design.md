## Context

The ReviewPage (`src/trailvideocut/ui/review_page.py`) currently has a bottom horizontal splitter at fixed 200px height containing two panels side by side:
- **Left**: "Selected Clip" group box (350px initial width) with a multi-line `QLabel` and prev/next navigation buttons.
- **Right**: "Plate Detection" group box (250px initial width) containing action buttons, filter settings, plate list, blur preview button, and progress bar.

The "Selected Clip" panel consumes significant space for information that could be shown inline. The prev/next buttons duplicate what clicking the timeline already does. The plate detection panel is squeezed horizontally, forcing a tall layout.

Additionally, in preview mode, `_on_clip_selected` calls `QMediaPlayer.setPosition()` followed by a direct `_on_music_position()` call. The async `positionChanged` signal can fire after the direct call with a slightly different position, causing the video to seek to the end of the previous clip.

## Goals / Non-Goals

**Goals:**
- Remove the "Selected Clip" group box and its prev/next navigation buttons entirely.
- Display selected clip info inline in the existing summary bar (`_summary` label) at the top of the ReviewPage.
- Expand the Plate Detection panel to full width of the bottom section.
- Reduce the bottom section height (from 200px to ~160px) to maximize video player area.
- Fix the preview mode clip selection race condition so clicking a clip positions the video at `clip.source_start`.

**Non-Goals:**
- Redesigning the Plate Detection panel controls or adding new features.
- Changing the timeline widget or video player behavior.
- Modifying the plate overlay widget.
- Making the bottom section resizable (it stays fixed height, just shorter).

## Decisions

### 1. Inline clip info in the summary bar

**Decision**: Extend the `_summary` QLabel text to append selected clip details after the existing summary stats, separated by a pipe `|` delimiter. When no clip is selected, only the base summary is shown.

**Format**: `Tempo: 120 BPM | Beats: 48 | Clips: 12 | CV: 0.123 | Duration: 30.0s  |  Clip 3/12  Score: 0.456  Src: 1.20-2.40s  Tgt: 3.50-4.70s`

**Rationale**: The summary bar already uses this pipe-delimited format. Appending clip info keeps the UI consistent and avoids creating new widgets. The monospace clip data naturally fits alongside the existing stats. Section label, energy, and plate info are included when a clip is selected.

**Alternative considered**: A separate label row below the summary. Rejected because it would add vertical space rather than saving it.

### 2. Full-width Plate Detection panel

**Decision**: Remove the `QSplitter` from the bottom section entirely. The Plate Detection `QGroupBox` becomes the sole child of the bottom area, occupying full width.

**Rationale**: Without the clip panel, there's no need for a splitter. The plate list (`QListWidget`) and button rows benefit from the extra horizontal space, allowing the group box height to be reduced.

### 3. Reduced bottom section height

**Decision**: Reduce `setFixedHeight` from 200px to 160px.

**Rationale**: With full width, the plate panel controls have more horizontal room. The plate list remains scrollable and usable at reduced height. The extra 40px goes to the video player.

### 4. Fix preview mode clip selection — pre-set clip index

**Decision**: In `_on_clip_selected` during preview mode, compute the preview clip index directly, set `_preview_clip_index` to it, and perform the video seek explicitly — rather than delegating to `_on_music_position`.

**Approach**:
1. Look up the clicked clip in `_preview_decisions` to get `clip_idx`.
2. Set `_preview_clip_index = clip_idx` before calling `setPosition` on the music player.
3. Seek the video directly to `clip.source_start`.
4. Update timeline selection and clip info.
5. When `positionChanged` fires from the music player, `_on_music_position` sees `clip_idx == _preview_clip_index` and only does drift correction — no re-seek.

**Rationale**: The root cause is a race condition: `setPosition` triggers `positionChanged` asynchronously with intermediate positions that can resolve to the previous clip. By pre-setting `_preview_clip_index`, the signal handler treats any incoming position as "same clip" and only corrects drift, preventing the wrong seek.

**Alternative considered**: Temporarily disconnecting `positionChanged` during the seek. Rejected because reconnecting after an async operation is fragile and could miss position updates.

## Risks / Trade-offs

- **[Summary bar width]** On narrow windows, the summary bar text may truncate when clip info is appended. → Mitigation: The summary label already handles overflow gracefully (Qt truncates with elision). The clip info is placed at the end so the global stats (Tempo, Beats, etc.) remain visible even when truncated.
- **[Plate panel height at 160px]** The plate list will show fewer visible items at the reduced height. → Mitigation: The list is scrollable; users typically interact with a few plates at a time. The trade-off of more video area is worth it.
- **[Preview seek timing]** Setting `_preview_clip_index` before the music player actually seeks means a brief window where the index is "ahead" of the music position. → Mitigation: `_on_music_position` only uses the index to decide whether to re-seek. During the brief window, it will do drift correction at most, which converges to the correct position.
