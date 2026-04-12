## Why

The ReviewPage bottom panel consumes 200px of fixed vertical space, reducing the video player area. The "Selected Clip" panel dedicates an entire group box (with prev/next navigation buttons) to information that can be displayed inline. Meanwhile, the Plate Detection panel is squeezed into the remaining horizontal space. Additionally, clicking a clip in preview mode positions the video at the end of the previous clip instead of the start of the selected clip, due to a race condition between `QMediaPlayer.setPosition` and the `positionChanged` signal handler.

## What Changes

- **Remove the "Selected Clip" group box panel** entirely, including the prev/next clip navigation buttons.
- **Display clip info inline** in the summary bar at the top (next to existing Tempo/Beats/Clips labels), using clear monospace font for the selected clip's key details (index, score, source/target times).
- **Expand the Plate Detection panel** to use the full horizontal width of the bottom section (no longer sharing with the clip panel), reducing its required height.
- **Reduce the bottom section height** from 200px to a smaller value that fits the now-wider plate detection layout, maximizing the video player area.
- **Fix preview mode clip selection positioning**: when a clip is selected in preview mode, the video must seek to `clip.source_start` (the beginning of the selected clip), not to the end of the previous clip.

## Capabilities

### New Capabilities
- `inline-clip-info`: Display selected clip information inline in the summary bar instead of a dedicated panel.

### Modified Capabilities
- `plate-overlay-ui`: The plate detection panel layout changes from sharing horizontal space with the clip panel to occupying the full width, requiring a reorganized layout of controls.

## Impact

- **Code**: `src/trailvideocut/ui/review_page.py` — major layout refactoring (remove clip group box, modify summary label, restructure plate panel layout, reduce bottom height, fix preview seek logic).
- **UI**: The bottom section will be shorter, the video player will be taller, and selected clip info moves to the top summary bar.
- **No API/dependency changes**: All changes are internal UI layout and a bug fix.
