## 1. Plate metadata embedding in OTIO

- [x] 1.1 Modify `DaVinciExporter.export()` to accept `plate_data: dict[int, ClipPlateData] | None`
- [x] 1.2 Filter plate detections to frames within each clip's source range and convert to clip-relative offsets
- [x] 1.3 Embed plate metadata under `clip.metadata["trailvideocut"]["plates"]` with fps and per-frame detections

## 2. DaVinci Resolve companion script generation

- [x] 2.1 Create `editor/resolve_script.py` with `generate_resolve_script()` function
- [x] 2.2 Implement Fusion composition creation: Blur + RectangleMask node chains with keyframed Center/Width/Height
- [x] 2.3 Implement delta-based keyframing — only set keyframes when plate position changes
- [x] 2.4 Auto-scale Fusion XBlurSize by relative plate area (1.0 smallest → 2.0 largest)
- [x] 2.5 Implement plate track grouping via nearest-center matching across frames
- [x] 2.6 Handle WSL path conversion in generated script (reuse _path_to_file_url pattern)

## 3. WSL interop execution

- [x] 3.1 Add `_is_wsl()` detection (check /proc/version for "microsoft")
- [x] 3.2 Add `_find_windows_python()` to locate Windows Python via standard paths
- [x] 3.3 Add `try_execute_resolve_script()` to run companion script via WSL interop with fallback

## 4. Export pipeline integration

- [x] 4.1 Pass `plate_data` from `RenderWorker.run()` to `DaVinciExporter.export()`
- [x] 4.2 Add `resolve_apply_blur` config field to `TrailVideoCutConfig`
- [x] 4.3 Wire script generation and WSL interop execution in `DaVinciExporter.export()`
- [x] 4.4 Wire `resolve_apply_blur` from render settings through `main_window.py`

## 5. Export page UI

- [x] 5.1 Add "Include plate blur data in OTIO" checkbox (visible in DaVinci mode only)
- [x] 5.2 Add "Auto-apply in Resolve" checkbox (sub-option)
- [x] 5.3 Wire checkbox state through `get_render_settings()` → `resolve_apply_blur`
- [x] 5.4 Update `set_finished()` to show companion script path when generated

## 6. Testing

- [x] 6.1 Test OTIO metadata embedding: plate data on correct clips with correct frame offsets
- [x] 6.2 Test frame number mapping: plates outside clip range excluded, absolute-to-relative correct
- [x] 6.3 Test companion script generation: valid Python with expected Fusion node structure
- [x] 6.4 Test WSL path handling in generated script
- [x] 6.5 Test edge cases: no plate data (no script), all blur_strength=0 (excluded)
- [x] 6.6 Manual test: run companion script with Resolve Studio 20+ open
