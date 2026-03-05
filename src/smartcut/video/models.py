from dataclasses import dataclass


@dataclass
class InterestScore:
    """Composite visual interest score for a time window."""

    optical_flow: float = 0.0
    color_change: float = 0.0
    edge_variance: float = 0.0
    brightness_change: float = 0.0

    @property
    def composite(self) -> float:
        """Weighted composite score."""
        return (
            self.optical_flow * 0.35
            + self.color_change * 0.25
            + self.edge_variance * 0.15
            + self.brightness_change * 0.25
        )

    def energy_weighted_composite(self, energy: float) -> float:
        """Composite score with weights biased by audio energy.

        High energy (>0.7): boosts optical_flow (action footage).
        Low energy (<0.3): boosts edge_variance (scenic footage).
        Mid energy: standard weights.
        """
        if energy > 0.7:
            return (
                self.optical_flow * 0.50
                + self.color_change * 0.25
                + self.edge_variance * 0.05
                + self.brightness_change * 0.20
            )
        elif energy < 0.3:
            return (
                self.optical_flow * 0.15
                + self.color_change * 0.20
                + self.edge_variance * 0.40
                + self.brightness_change * 0.25
            )
        else:
            return self.composite


@dataclass
class VideoSegment:
    """A scored segment of the source video."""

    start_time: float
    end_time: float
    interest: InterestScore
    scene_boundary_near: bool = False

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def midpoint(self) -> float:
        return (self.start_time + self.end_time) / 2.0
