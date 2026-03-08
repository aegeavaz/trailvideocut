from scenedetect import open_video, SceneManager, ContentDetector

from trailvideocut.config import TrailVideoCutConfig


class SceneBoundaryDetector:
    """Detect gradual scene transitions using PySceneDetect."""

    def __init__(self, config: TrailVideoCutConfig):
        self.config = config

    def detect_boundaries(self) -> list[float]:
        """Return list of scene boundary timestamps (seconds)."""
        video = open_video(str(self.config.video_path))
        sm = SceneManager()
        sm.add_detector(ContentDetector(threshold=self.config.scene_detect_threshold))
        sm.detect_scenes(video)
        scene_list = sm.get_scene_list()
        boundaries = [scene_start.get_seconds() for scene_start, _ in scene_list]
        return boundaries
