"""Smoke test: PlateDetectionWorker forwards phone_zones through its finished signal.

Verifies that zones recorded by the detector are carried on the emitted
`ClipPlateData` without needing a separate signal.
"""

from unittest.mock import MagicMock, patch


from trailvideocut.plate.models import ClipPlateData, PlateBox


def test_worker_emits_phone_zones_on_finished(qapp):
    from trailvideocut.ui.workers import PlateDetectionWorker

    zones = {42: [(0.1, 0.2, 0.3, 0.4)], 60: [(0.5, 0.5, 0.2, 0.2)]}
    plate_data = ClipPlateData(
        clip_index=0,
        detections={42: [PlateBox(x=0.9, y=0.9, w=0.01, h=0.01, confidence=0.9)]},
        phone_zones=zones,
    )

    detector = MagicMock()
    detector.detect_clip.return_value = plate_data

    received: dict = {}

    def on_finished(results):
        received.update(results)

    with patch("trailvideocut.plate.detector.PlateDetector", return_value=detector):
        worker = PlateDetectionWorker(
            video_path="fake.mp4",
            clips=[(0, 0.0, 1.0)],
            model_path="fake.onnx",
            exclude_phones=True,
        )
        worker.finished.connect(on_finished)
        worker.run()  # run inline (no thread) for deterministic test

    assert 0 in received
    assert received[0].phone_zones == zones
