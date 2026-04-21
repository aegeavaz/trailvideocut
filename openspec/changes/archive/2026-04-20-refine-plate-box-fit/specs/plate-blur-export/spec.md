## ADDED Requirements

### Requirement: Oriented-rectangle blur masks
When a plate box carries a non-zero rotation angle, the system SHALL apply the Gaussian blur through a mask whose blurred region is the rotated rectangle defined by `(centre_x, centre_y, width, height, angle)` rather than an axis-aligned bounding rectangle. The rotated-rectangle mask SHALL be produced by computing the four corner points via `cv2.boxPoints` and filling the convex polygon on a same-sized mask with `cv2.fillConvexPoly`, then applying the blur through that mask.

#### Scenario: Pixels outside the rotated polygon are unblurred
- **WHEN** a frame contains a single plate box with `angle = 20°` rendered by the MP4 export path
- **THEN** pixels inside the rotated quadrilateral defined by `(centre, width, height, 20°)` SHALL be blurred in the exported output, and pixels outside that quadrilateral but inside the box's axis-aligned envelope SHALL NOT be blurred (they SHALL match the source frame modulo encoding rounding)

#### Scenario: Axis-aligned boxes remain unaffected
- **WHEN** a frame contains only plate boxes with `angle == 0.0`
- **THEN** the blur output SHALL be pixel-identical to the pre-feature axis-aligned blur path (no behavioural regression)

### Requirement: Kernel sizing for oriented boxes uses the rotated rectangle's own dimensions
The Gaussian blur kernel size for a rotated-rectangle mask SHALL be computed from the rotated rectangle's own `width` and `height` (the plate-aligned extents), using the same formula as axis-aligned boxes: `kernel_size = max(3, min(plate_pixel_w, plate_pixel_h))`, rounded up to the nearest odd value. The kernel SHALL NOT be derived from the axis-aligned bounding envelope of the rotated rectangle.

#### Scenario: Rotated kernel matches plate-aligned dimensions
- **WHEN** a plate has rotated-rectangle dimensions 160×40 px at `angle = 25°` (its axis-aligned envelope would be larger)
- **THEN** the Gaussian kernel size SHALL be derived from `min(160, 40) == 40`, yielding an odd kernel size ≤ 40 — the same result as if the plate were axis-aligned at 160×40

### Requirement: Drift-tolerant union for oriented boxes
The existing drift-tolerant blur behaviour (unioning boxes at frames N-1, N, and N+1) SHALL extend to oriented boxes by unioning the rotated polygons on the same mask. The union SHALL be computed by filling each neighbour's rotated polygon onto the single mask before applying the blur. The union SHALL NOT fall back to each box's axis-aligned envelope when any participant is oriented.

#### Scenario: Oriented neighbours are polygon-unioned
- **WHEN** frame N has a plate at `angle = 10°` and frame N-1 has the same plate at a slightly different centre with `angle = 10°`
- **THEN** the mask applied at frame N SHALL be the union of the two rotated polygons, and pixels outside the union SHALL NOT be blurred
