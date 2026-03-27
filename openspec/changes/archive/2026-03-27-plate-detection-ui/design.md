## Context

TrailVideoCut is a PySide6 desktop app that analyzes trail camera footage, selects interesting segments synced to music, and renders the final edit. The Review page already displays a timeline of clips with a video player. Users want to detect license plates in the video for privacy blurring or identification. Currently there is no object detection capability in the app.

The app already uses OpenCV extensively for frame scoring (optical flow, color histograms, edge detection) and supports GPU acceleration via CuPy. The UI uses a `QVideoWidget` for playback with custom painted overlays on the timeline. Background processing is handled via `QThread`-based workers (`AnalysisWorker`, `RenderWorker`).

## Goals / Non-Goals

**Goals:**
- Detect license plates automatically in video clips using a pre-trained model
- Display detected plate bounding boxes as overlays on the video player
- Allow interactive correction: select, move, resize, delete bounding boxes
- Allow manual addition of bounding boxes on frames where detection failed
- Run detection as a non-blocking background operation with progress feedback
- Scope detection to selected clip or all clips

**Non-Goals:**
- OCR / reading plate text (detection only, not recognition)
- Real-time detection during playback (detection is a batch pre-processing step)
- CLI support (UI-only feature)
- Automatic privacy blurring (future feature that would consume detection data)
- Training custom models (use pre-trained weights only)

## Decisions

### 1. Detection Engine: OpenCV DNN with ONNX model

**Choice**: Use OpenCV's DNN module (`cv2.dnn.readNetFromONNX`) with a pre-trained YOLOv8n plate detection ONNX model.

**Alternatives considered:**
- **ultralytics (YOLOv8 Python package)**: Easier API, but adds a heavy dependency (~200MB+ with PyTorch). Overkill for inference-only use.
- **OpenCV Haar cascades**: Already bundled, but poor accuracy for plates at varying angles/distances.

**Rationale**: OpenCV is already a dependency. Loading an ONNX model keeps the dependency footprint minimal. A YOLOv8-nano ONNX model (~6MB) provides good accuracy at fast inference speed. Users download the model once on first use.

### 2. Overlay Rendering: Custom QWidget overlay on QVideoWidget

**Choice**: Create a transparent `QWidget` that sits on top of the `QVideoWidget` and paints bounding boxes using `QPainter`. The overlay handles mouse events for selection, drag-to-move, and resize handles.

**Alternatives considered:**
- **QGraphicsView/QGraphicsScene**: Full scene graph with built-in item selection/transform. More powerful but requires replacing the current `QVideoWidget` with a `QGraphicsVideoItem` — significant refactor.
- **OpenGL overlay**: Would work with the existing D3D11/OpenGL backend but adds complexity and platform-specific issues.

**Rationale**: A transparent overlay widget is the least invasive approach. It composes naturally with the existing `QVideoWidget`, requires no refactoring of the video player, and `QPainter` provides all needed drawing primitives. Mouse event handling is straightforward with `QWidget` events.

### 3. Detection Data Model: Per-clip frame-indexed dictionary

**Choice**: Store detection results as a dictionary mapping frame numbers to lists of bounding boxes. Each bounding box is stored in normalized coordinates (0-1 range relative to video dimensions) to be resolution-independent.

```python
@dataclass
class PlateBox:
    x: float       # normalized left (0-1)
    y: float       # normalized top (0-1)
    w: float       # normalized width (0-1)
    h: float       # normalized height (0-1)
    confidence: float
    manual: bool   # True if user-added, False if auto-detected

@dataclass
class ClipPlateData:
    clip_index: int
    detections: dict[int, list[PlateBox]]  # frame_number -> boxes
```

**Rationale**: Normalized coordinates decouple detection from display resolution. Frame-indexed storage allows efficient lookup during playback. The `manual` flag distinguishes user corrections from auto-detections for potential future re-detection without losing manual annotations.

### 4. Background Worker: Dedicated PlateDetectionWorker (QThread)

**Choice**: Create a new `PlateDetectionWorker` following the same pattern as `AnalysisWorker` — a `QThread` subclass that emits progress signals and can be cancelled.

**Rationale**: Consistent with existing architecture. Detection on a full clip can take seconds to minutes depending on frame count and hardware. The worker emits per-frame progress and returns results via signal on completion.

### 5. Manual Box Addition: Clone from last detected plate

**Choice**: When the user adds a manual box, pre-populate its position and size from the nearest detected plate box (searching backward in frame order from the current frame). If no prior detection exists, use a default centered box.

**Rationale**: Plates typically remain in similar positions across consecutive frames. Cloning from the last detection provides a good starting point that the user only needs to fine-tune.

### 6. Coordinate Mapping: Video frame to widget space

**Choice**: The overlay widget maps between normalized plate coordinates and widget pixel coordinates using the video's aspect ratio and the widget's current size, accounting for letterboxing that `QVideoWidget` may apply.

**Rationale**: The video may be displayed at a different size than its native resolution, and `QVideoWidget` letterboxes to maintain aspect ratio. The overlay must compute the actual video display rect within the widget to correctly position boxes.

## Risks / Trade-offs

- **[Model accuracy]** Pre-trained plate detection models vary in quality across camera angles, lighting, and plate styles. → Mitigation: The manual correction workflow (move, resize, add, delete) compensates for detection errors. Users can always override the algorithm.

- **[Model download]** First-run requires downloading the ONNX model file. → Mitigation: Bundle a small fallback or prompt user to download. Show clear progress during download. Cache in a platform-appropriate data directory.

- **[Overlay performance]** Painting many boxes during playback could cause frame drops. → Mitigation: Only the current frame's boxes are painted. Typical plate count per frame is 0-3. `QPainter` can easily handle this at 30fps.

- **[QVideoWidget overlay stacking]** On some platforms, `QVideoWidget` renders via a native surface that can paint over child widgets. → Mitigation: Use `setAttribute(Qt.WA_TransparentForMouseEvents, False)` and `raise_()` on the overlay. If platform issues persist, fall back to `QGraphicsVideoItem` approach.

- **[Frame extraction during detection]** OpenCV reads frames separately from PySide6's `QMediaPlayer`. Frame numbering must align. → Mitigation: Use the video's FPS to convert between timestamps and frame indices. Both OpenCV and the player use the same source file.
