## ADDED Requirements

### Requirement: Fusion comp-frame keyframes preserve source-frame alignment
The generated DaVinci Lua script SHALL map each plate detection at clip-relative source-frame index `rel` to a Fusion keyframe at comp frame `comp_for_rel(rel) = clip_offset + rel`, where `clip_offset = SRC_START_FRAME + MediaIn1.ClipTimeStart` (the latter compensating for Resolve's crossfade leading handle frames). No additive, subtractive, or piecewise-keyframe-conditional correction term SHALL be applied beyond `clip_offset`. Any future re-introduction of such a term requires concrete, documented evidence that Resolve's timeline-to-source mapping introduces that exact offset, and the condition must be recorded as a comment in the generator with the clip used to verify it.

#### Scenario: Keyframe for plate at clip-relative source frame K
- **WHEN** a plate detection exists at clip-relative source frame K for a clip placed at comp offset `clip_offset`
- **THEN** the Lua script SHALL set the mask Center/Width/Height keyframe at comp frame `clip_offset + K`, matching the same `boxes[K]` the preview overlay displays at that source frame and the same `boxes[K]` the MP4 export writes

#### Scenario: No spurious offset regardless of source-video origin
- **WHEN** a clip has plate detections at source frames K1 < K2 < K3 and the source video was either natively captured or concatenated from multiple source files
- **THEN** the Lua keyframes SHALL land at `clip_offset + K1`, `clip_offset + K2`, `clip_offset + K3` with no additional conditional offset, matching the MP4 export's pixel-level alignment at the same source frames
