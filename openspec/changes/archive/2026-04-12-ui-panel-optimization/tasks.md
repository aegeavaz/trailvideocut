## 1. Remove Selected Clip panel

- [x] 1.1 Delete the "Selected Clip" `QGroupBox` creation code: `clip_group`, `clip_layout`, `_clip_info` label, `_btn_prev_clip`, `_btn_next_clip` buttons, `clip_nav` layout, and the `bottom_splitter.addWidget(clip_group)` call in `review_page.py` `__init__`.
- [x] 1.2 Delete the `_prev_clip()` and `_next_clip()` methods.
- [x] 1.3 Remove all references to `_clip_info`, `_btn_prev_clip`, `_btn_next_clip` across the class (setText calls, enable/disable calls, etc.).

## 2. Inline clip info in summary bar

- [x] 2.1 Add a `_base_summary` instance variable to store the base summary text (Tempo/Beats/Clips/CV/Duration) set in `set_data()`.
- [x] 2.2 Refactor `_show_clip_info(index)` to update `_summary` label by appending clip details after `_base_summary` with a pipe separator, instead of writing to the removed `_clip_info` label.
- [x] 2.3 Update all call sites that set `_clip_info.setText("No clip selected")` or similar to instead call `_summary.setText(self._base_summary)` to restore the base summary when no clip is selected.

## 3. Expand Plate Detection panel to full width

- [x] 3.1 Replace the `QSplitter` (`bottom_splitter`) with the Plate Detection `QGroupBox` (`plate_group`) added directly to `root` layout. Remove splitter creation, `setSizes`, and `setFixedHeight` from the splitter.
- [x] 3.2 Set `plate_group.setFixedHeight(160)` to replace the old 200px splitter height.
- [x] 3.3 Add `plate_group` to `root` layout with `stretch=0`.

## 4. Fix preview mode clip selection positioning

- [x] 4.1 In `_on_clip_selected()` preview branch: find the clip's index in `_preview_decisions`, set `_preview_clip_index` to that index, seek the video player directly to `clip.source_start`, and update timeline selection and clip info — instead of delegating to `_on_music_position()`.
- [x] 4.2 Keep `_music_player.setPosition()` call so the music seeks to the correct target position, but the `positionChanged` signal handler will see `_preview_clip_index` already correct and skip re-seeking.

## 5. Testing and verification

- [ ] 5.1 Launch the app and verify the ReviewPage layout: no "Selected Clip" panel, plate panel at full width, reduced bottom section height, larger video player area.
- [ ] 5.2 Click clips on the timeline and verify clip info appears inline in the summary bar with correct formatting.
- [ ] 5.3 Deselect clips (seek to non-clip area) and verify the summary bar reverts to base stats only.
- [ ] 5.4 Enter preview mode, click different clips on the timeline, and verify the video positions at the start of the selected clip (not the end of the previous one).
- [ ] 5.5 Verify plate detection controls remain fully functional at the new panel width and height.
  Note: PySide6 is not available in this environment. Manual UI testing required.
