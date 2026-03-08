import cv2
import numpy as np


def score_optical_flow(prev_gray: np.ndarray, curr_gray: np.ndarray) -> float:
    """Compute optical flow magnitude between two grayscale frames.

    Higher values = more motion (speed changes, curves, turns).
    """
    flow = cv2.calcOpticalFlowFarneback(
        prev_gray,
        curr_gray,
        None,
        pyr_scale=0.5,
        levels=3,
        winsize=15,
        iterations=3,
        poly_n=5,
        poly_sigma=1.2,
        flags=0,
    )
    magnitude, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
    return float(np.mean(magnitude))


def score_color_histogram_change(prev_frame: np.ndarray, curr_frame: np.ndarray) -> float:
    """Compare color histograms between two frames.

    Higher values = more scenery change.
    """
    prev_hsv = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2HSV)
    curr_hsv = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2HSV)
    hist_prev = cv2.calcHist([prev_hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
    hist_curr = cv2.calcHist([curr_hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
    cv2.normalize(hist_prev, hist_prev)
    cv2.normalize(hist_curr, hist_curr)
    correlation = cv2.compareHist(hist_prev, hist_curr, cv2.HISTCMP_CORREL)
    return float(max(0.0, 1.0 - correlation))


def score_edge_variance(frame_gray: np.ndarray) -> float:
    """Compute edge density as a proxy for visual detail/complexity."""
    edges = cv2.Canny(frame_gray, 50, 150)
    return float(np.mean(edges) / 255.0)


def score_brightness_change(prev_gray: np.ndarray, curr_gray: np.ndarray) -> float:
    """Measure absolute change in mean brightness.

    Detects tunnel entry/exit, shadows, open fields.
    """
    prev_brightness = float(np.mean(prev_gray))
    curr_brightness = float(np.mean(curr_gray))
    return abs(curr_brightness - prev_brightness) / 255.0
