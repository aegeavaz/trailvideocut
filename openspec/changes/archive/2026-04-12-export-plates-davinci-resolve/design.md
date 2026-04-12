## Context

The app currently exports two formats: MP4 (with blur baked in) and OTIO (timeline-only, for DaVinci Resolve). The OTIO export preserves edit structure but discards all plate detection data. Users who want to finish editing in Resolve must manually recreate blur regions, even though the app already has per-frame plate bounding boxes with blur strength.

The app runs on WSL while DaVinci Resolve runs on Windows. DaVinci Resolve's scripting API (`DaVinciResolveScript`) uses native IPC (`fusionscript.dll`) which cannot cross the WSL boundary directly. However, WSL interop allows calling Windows executables from WSL, and those Windows-native processes CAN connect to Resolve's IPC.

DaVinci Resolve 20+ supports:
- **OTIO import**: Timeline structure only (clips, transitions, media references) — no native effect support from OTIO metadata
- **Fusion compositions**: Node-based compositing with Blur nodes and keyframeable RectangleMask — the primary way to do animated region blur
- **DaVinciResolveScript API** (Studio edition): External Python scripting to programmatically manipulate timelines, add Fusion compositions, and set keyframes

The plate data model stores per-frame bounding boxes as `ClipPlateData.detections: dict[int, list[PlateBox]]` where keys are absolute source-video frame numbers and PlateBox contains normalized coordinates (0-1) plus blur_strength.

## Goals / Non-Goals

**Goals:**
- Transport plate blur data from the app to DaVinci Resolve with minimum user friction
- Auto-apply blur in Resolve via WSL interop when Resolve Studio is running
- Fall back gracefully to a companion script when auto-apply is unavailable
- Preserve per-plate blur strength and per-frame position data
- Target DaVinci Resolve 20+ compatibility
- Maintain backward compatibility — existing OTIO export works unchanged when plate export is disabled

**Non-Goals:**
- Modifying DaVinci Resolve's behavior or requiring plugins
- Supporting other NLEs (Premiere, FCP) — out of scope for this change
- Baking blur into the OTIO export (that's what MP4 export does)
- Real-time preview of Resolve blur settings
- Supporting DaVinci's Color page Power Windows (Fusion is more flexible and scriptable)

## Decisions

### Decision 1: WSL interop with script fallback

**Choice**: Embed plate data as OTIO clip metadata, generate a companion Python script, and attempt to execute it automatically via WSL interop (calling Windows Python which can use Resolve's native IPC).

**Why**: Maximum automation with graceful degradation. When Resolve Studio is running, the user gets one-click blur application. When it's not available (Resolve not running, Free edition, no Windows Python), the companion script is saved for manual execution later.

**Architecture**:
```
trailvideocut (WSL)
  ├─ 1. Write OTIO with plate metadata in clip metadata
  ├─ 2. Generate companion script (_resolve_plates.py)
  └─ 3. Execute via WSL interop: /mnt/c/.../python.exe script.py
         └─ Script (Windows native) → DaVinciResolveScript IPC → Resolve
```

**Alternatives considered**:
- *Manual script only*: More friction — user must find and run the script themselves.
- *FCPXML with effects*: DaVinci imports FCPXML, but its effect model doesn't map cleanly to animated blur masks.
- *Direct IPC from WSL*: Impossible — `fusionscript.dll` requires a native Windows process.

### Decision 2: Fusion Blur + RectangleMask per plate

**Choice**: Each plate gets its own Blur node with a RectangleMask in a Fusion composition chain.

**Why**: Fusion's RectangleMask maps directly to the plate bounding box (Center, Width, Height). Multiple plates are handled by chaining blur nodes. This is the standard Resolve 20+ workflow for region-specific effects.

**Node chain per clip**:
```
MediaIn → Blur1(RectangleMask1) → Blur2(RectangleMask2) → ... → MediaOut
```

Each Blur node's RectangleMask has keyframed Center, Width, Height matching the per-frame plate data.

### Decision 3: Frame number mapping strategy

**Choice**: Convert absolute source-video frame numbers to clip-relative frame offsets during OTIO metadata embedding.

**Why**: Each OTIO clip has a `source_range` with a start time. The Fusion composition operates in clip-local time. Frame N in the plate data corresponds to `(N - clip_source_start_frame)` in Fusion time. This translation happens once at export time.

**Formula**: `fusion_frame = abs_frame - int(clip_source_start_seconds * fps)`

### Decision 4: Blur size auto-scaling by relative plate area

**Choice**: Auto-scale XBlurSize based on relative plate bounding-box area within the clip. The `blur_strength` field is used only for inclusion/exclusion (plates with `blur_strength <= 0` are excluded upstream) and no longer drives the blur size value.

**Formula**: `blur_size = 1.0 + (area - min_area) / (max_area - min_area)` where `area = w * h` and min/max are computed across all tracks and frames in the clip. When all plates have the same area, `blur_size = 1.0`.

The range [1.0, 2.0] produces consistent blur across resolutions: 1.0 for the smallest plate in a clip, 2.0 for the largest.

### Decision 5: Coordinate mapping (PlateBox → Fusion RectangleMask)

**Choice**: Direct normalized coordinate mapping with Y-axis inversion.

- Center: `(x + w/2, 1.0 - (y + h/2))` — Fusion Y=0 is bottom, PlateBox Y=0 is top
- Width: `w` (already normalized 0-1)
- Height: `h` (already normalized 0-1)

### Decision 6: Plate track grouping

**Choice**: Group per-frame boxes into spatial tracks via nearest-center matching (max distance 0.1 normalized).

**Why**: `ClipPlateData.detections` has no persistent plate IDs. The companion script must group boxes into tracks (one physical plate across frames) to create one Blur+Mask pair per track. This matches the existing logic in `expand_boxes_for_drift()`.

## Risks / Trade-offs

- **[Resolve Studio required]** → The DaVinciResolveScript API only works with Studio edition. Free edition users get the OTIO + script but cannot auto-apply. Mitigation: Clear messaging in UI and script header.
- **[DaVinci API stability]** → The scripting API is not formally versioned. Mitigation: Target Resolve 20+, keep script simple.
- **[Fusion keyframe volume]** → Many plates across thousands of frames generates many keyframes. Mitigation: Delta-based keyframing — only keyframe when position changes from previous frame.
- **[WSL interop may fail]** → Windows Python may not be installed, or interop may be disabled. Mitigation: Graceful fallback with clear user-facing message and script path.
- **[OTIO file size]** → Embedding per-frame plate data increases file size (~2MB for a 10-min video). Mitigation: Acceptable; omit unchanged frames via delta encoding.
