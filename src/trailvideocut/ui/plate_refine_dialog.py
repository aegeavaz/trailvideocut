"""Review dialog for accepting/rejecting plate-refinement results.

Shown after a :class:`PlateRefineWorker` finishes. The user can accept or
revert each frame's refinement individually, bulk-accept high-confidence
results, or revert everything.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from trailvideocut.plate.models import PlateBox


@dataclass
class RefinementEntry:
    """One row of the review dialog."""

    frame_no: int
    box_idx: int
    before: PlateBox
    after: PlateBox
    confidence: float
    method: str
    accepted: bool = False


def _render_thumbnail(
    frame: np.ndarray,
    before: PlateBox,
    after: PlateBox,
    width: int = 480,
    crop_pad: float = 0.6,
) -> QPixmap:
    """Draw the before (red) and after (green) polygons on a thumbnail cropped
    around the box — full-frame thumbs are too small to see the plate.
    """
    h, w = frame.shape[:2]

    # Pad the envelope by ``crop_pad`` of its size on each side so both the
    # before and after boxes are visible with context, then clamp to frame.
    env_x, env_y, env_w, env_h = before.aabb_envelope()
    after_env = after.aabb_envelope()
    union_x0 = min(env_x, after_env[0])
    union_y0 = min(env_y, after_env[1])
    union_x1 = max(env_x + env_w, after_env[0] + after_env[2])
    union_y1 = max(env_y + env_h, after_env[1] + after_env[3])
    ux = int(round(max(0.0, union_x0 - crop_pad * (union_x1 - union_x0)) * w))
    uy = int(round(max(0.0, union_y0 - crop_pad * (union_y1 - union_y0)) * h))
    ux2 = int(round(min(1.0, union_x1 + crop_pad * (union_x1 - union_x0)) * w))
    uy2 = int(round(min(1.0, union_y1 + crop_pad * (union_y1 - union_y0)) * h))
    if ux2 - ux < 16 or uy2 - uy < 16:
        ux, uy, ux2, uy2 = 0, 0, w, h
    crop = frame[uy:uy2, ux:ux2]

    crop_h, crop_w = crop.shape[:2]
    scale = width / max(1, crop_w)
    small = cv2.resize(crop, (int(crop_w * scale), int(crop_h * scale)))

    def _draw(img, box: PlateBox, color):
        corners = []
        for cx, cy in box.corners_px(w, h):
            # Map frame coords → cropped coords → scaled coords.
            corners.append(
                [int(round((cx - ux) * scale)), int(round((cy - uy) * scale))],
            )
        cv2.polylines(
            img, [np.array(corners, dtype=np.int32)],
            isClosed=True, color=color, thickness=2,
        )

    _draw(small, before, (80, 80, 255))  # BGR red-ish
    _draw(small, after, (80, 220, 80))   # BGR green-ish

    rgb = small[:, :, ::-1].copy()
    hh, ww = rgb.shape[:2]
    img = QImage(rgb.data, ww, hh, ww * 3, QImage.Format_RGB888)
    return QPixmap.fromImage(img.copy())


class PlateRefineReviewDialog(QDialog):
    """Modal dialog for the user to accept/revert refinement results.

    Accepts refinements as a list of :class:`RefinementEntry`. On ``accept()``,
    :attr:`accepted_entries` contains only the entries the user kept.
    """

    def __init__(
        self,
        entries: list[RefinementEntry],
        frame_lookup=None,
        high_confidence_threshold: float = 0.8,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Review plate refinements")
        self._entries = list(entries)
        self._high_confidence_threshold = high_confidence_threshold
        self.resize(900, 600)

        layout = QVBoxLayout(self)

        intro = QLabel(
            f"{len(self._entries)} refinement(s). Every row is checked by "
            f"default — uncheck any row whose refined box you'd rather revert. "
            f"<b>Red</b> = original, <b>green</b> = refined.",
        )
        intro.setTextFormat(Qt.RichText)
        layout.addWidget(intro)

        self._table = QTableWidget(len(self._entries), 5, self)
        self._table.setHorizontalHeaderLabels(
            ["Accept", "Frame", "Method", "Confidence", "Preview"],
        )
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        # Big enough to show ~300px-tall thumbnails cropped around the plate.
        self._table.verticalHeader().setDefaultSectionSize(300)
        self._table.setColumnWidth(0, 60)
        self._table.setColumnWidth(1, 70)
        self._table.setColumnWidth(2, 90)
        self._table.setColumnWidth(3, 100)
        self._table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.Stretch,
        )

        self._checkboxes: list[QCheckBox] = []
        self._thumbnail_labels: dict[int, QLabel] = {}
        for row, entry in enumerate(self._entries):
            cb = QCheckBox()
            # Pre-tick every row so the default OK path applies the
            # refinements — the user opts out of individual ones rather than
            # opting in to each.
            cb.setChecked(True)
            self._checkboxes.append(cb)
            # Wrap the checkbox in a cell widget so it can be centred.
            cb_cell = QWidget()
            cb_layout = QHBoxLayout(cb_cell)
            cb_layout.addWidget(cb)
            cb_layout.setAlignment(Qt.AlignCenter)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            self._table.setCellWidget(row, 0, cb_cell)

            self._table.setItem(row, 1, QTableWidgetItem(str(entry.frame_no)))
            self._table.setItem(row, 2, QTableWidgetItem(entry.method))
            self._table.setItem(
                row, 3, QTableWidgetItem(f"{entry.confidence:.2f}"),
            )
            # Placeholder cell that the caller populates asynchronously via
            # :meth:`set_thumbnail`. Shown as "loading..." until the frame
            # is decoded so the dialog can open instantly.
            cell = QLabel("loading...")
            cell.setAlignment(Qt.AlignCenter)
            self._thumbnail_labels[row] = cell
            self._table.setCellWidget(row, 4, cell)

            # Eager-populate if a synchronous ``frame_lookup`` is supplied
            # (back-compat for tests / callers that pre-decode).
            if frame_lookup is not None:
                frame = frame_lookup(entry.frame_no)
                if frame is not None:
                    self.set_thumbnail(
                        row, _render_thumbnail(
                            frame, entry.before, entry.after,
                        ),
                    )
        layout.addWidget(self._table)

        # Bulk action row.
        bulk = QHBoxLayout()
        accept_hc = QPushButton(
            f"Accept all high-confidence (≥ {high_confidence_threshold:.2f})",
        )
        accept_hc.clicked.connect(self._accept_high_confidence)
        revert_all = QPushButton("Revert all")
        revert_all.clicked.connect(self._revert_all)
        accept_all = QPushButton("Accept all")
        accept_all.clicked.connect(self._accept_all)
        bulk.addWidget(accept_hc)
        bulk.addWidget(accept_all)
        bulk.addWidget(revert_all)
        bulk.addStretch()
        layout.addLayout(bulk)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def set_thumbnail(self, row: int, pixmap: QPixmap) -> None:
        """Populate the preview cell for *row* — called by the caller after
        it asynchronously decodes each frame."""
        label = self._thumbnail_labels.get(row)
        if label is not None:
            label.setText("")
            label.setPixmap(pixmap)

    def _accept_high_confidence(self) -> None:
        for cb, entry in zip(self._checkboxes, self._entries):
            cb.setChecked(entry.confidence >= self._high_confidence_threshold)

    def _accept_all(self) -> None:
        for cb in self._checkboxes:
            cb.setChecked(True)

    def _revert_all(self) -> None:
        for cb in self._checkboxes:
            cb.setChecked(False)

    @property
    def accepted_entries(self) -> list[RefinementEntry]:
        """The entries the user ticked when :meth:`accept` fired.

        Reads from the checkbox state so it's valid after ``exec_()`` returns.
        """
        out: list[RefinementEntry] = []
        for cb, entry in zip(self._checkboxes, self._entries):
            entry.accepted = cb.isChecked()
            if entry.accepted:
                out.append(entry)
        return out
