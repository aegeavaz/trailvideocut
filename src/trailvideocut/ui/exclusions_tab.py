"""Excluded sub-tab: edit exclusion ranges on the Setup page.

The widget is stateless about persistence — the parent SetupPage wires
``ranges_changed`` to the sidecar save/load and to the scrubber overlay.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def _fmt_time(t: float) -> str:
    """Format seconds as ``HH:MM:SS.ss``."""
    hours, rem = divmod(max(0.0, t), 3600)
    mins, secs = divmod(rem, 60)
    return f"{int(hours):02d}:{int(mins):02d}:{secs:05.2f}"


class ExclusionsTab(QWidget):
    """Setup-page tab for adding, viewing, and deleting exclusion ranges.

    - ``set_player_position(t)`` keeps the widget aware of the current player
      time, so Start/End buttons can capture it without reaching into the
      parent.
    - ``set_ranges(ranges)`` replaces the current list (e.g. on video open).
    - ``ranges`` returns a sorted list of ``(start, end)`` tuples.
    - ``ranges_changed`` fires whenever the list mutates (add, remove,
      clear) with the new full sorted list.
    """

    ranges_changed = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ranges: list[tuple[float, float]] = []
        self._pending_start: float | None = None
        self._current_position: float = 0.0
        self._build_ui()

    # --- public API ---

    @property
    def ranges(self) -> list[tuple[float, float]]:
        return list(self._ranges)

    def set_ranges(self, ranges: list[tuple[float, float]]) -> None:
        """Replace the current range list (does NOT emit ``ranges_changed``)."""
        self._ranges = sorted(
            ((float(s), float(e)) for s, e in ranges if s < e),
            key=lambda r: r[0],
        )
        self._pending_start = None
        self._refresh_ui()

    def set_player_position(self, t: float) -> None:
        """Remember the current player position (seconds) for Start/End capture."""
        self._current_position = float(t)

    # --- UI construction ---

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        btn_row = QHBoxLayout()
        self._btn_start = QPushButton("Start (I)")
        self._btn_start.setToolTip("Mark the in-point at the current player position")
        self._btn_start.clicked.connect(self._on_start_clicked)

        self._btn_end = QPushButton("End (O)")
        self._btn_end.setToolTip("Commit range from the pending Start to the current position")
        self._btn_end.clicked.connect(self._on_end_clicked)

        self._btn_clear = QPushButton("Clear All")
        self._btn_clear.clicked.connect(self._on_clear_clicked)

        btn_row.addWidget(self._btn_start)
        btn_row.addWidget(self._btn_end)
        btn_row.addWidget(self._btn_clear)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(
            "color: #b0b0b0; font-size: 12px; font-family: monospace;"
        )
        root.addWidget(self._status_label)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
        )
        self._chip_container = QWidget()
        self._chip_layout = QHBoxLayout(self._chip_container)
        self._chip_layout.setContentsMargins(0, 0, 0, 0)
        self._chip_layout.setSpacing(6)
        self._chip_layout.addStretch()
        self._scroll.setWidget(self._chip_container)
        root.addWidget(self._scroll)

    # --- Keyboard helpers (called from parent SetupPage shortcuts) ---

    def capture_start(self) -> None:
        self._on_start_clicked()

    def capture_end(self) -> None:
        self._on_end_clicked()

    def cancel_pending(self) -> None:
        if self._pending_start is not None:
            self._pending_start = None
            self._set_status("Pending Start cancelled.")
            self._refresh_ui()

    # --- Button handlers ---

    def _on_start_clicked(self):
        self._pending_start = self._current_position
        self._set_status(
            f"Pending Start at {_fmt_time(self._current_position)} — "
            "press End (O) to commit or Esc to cancel."
        )
        self._refresh_ui()

    def _on_end_clicked(self):
        if self._pending_start is None:
            self._set_status("Press Start (I) first to set the in-point.")
            return
        end = self._current_position
        start = self._pending_start
        if end <= start:
            self._set_status(
                f"End ({_fmt_time(end)}) must be after Start ({_fmt_time(start)})."
            )
            self._pending_start = None
            self._refresh_ui()
            return
        self._pending_start = None
        self._insert_range(start, end)
        self._set_status(f"Added range {_fmt_time(start)} → {_fmt_time(end)}.")

    def _on_clear_clicked(self):
        if not self._ranges:
            return
        res = QMessageBox.question(
            self,
            "Clear Exclusions",
            "Remove all exclusion ranges?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if res != QMessageBox.Yes:
            return
        self._ranges.clear()
        self._pending_start = None
        self._set_status("All ranges cleared.")
        self._refresh_ui()
        self.ranges_changed.emit(self.ranges)

    def _remove_range(self, idx: int):
        if 0 <= idx < len(self._ranges):
            removed = self._ranges.pop(idx)
            self._set_status(
                f"Removed range {_fmt_time(removed[0])} → {_fmt_time(removed[1])}."
            )
            self._refresh_ui()
            self.ranges_changed.emit(self.ranges)

    def _insert_range(self, start: float, end: float) -> None:
        self._ranges.append((start, end))
        self._ranges.sort(key=lambda r: r[0])
        self._refresh_ui()
        self.ranges_changed.emit(self.ranges)

    def _set_status(self, message: str) -> None:
        self._status_label.setText(message)

    # --- Chip rendering ---

    def _refresh_ui(self):
        while self._chip_layout.count():
            item = self._chip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        chip_style = (
            "QPushButton { border-radius: 12px; padding: 4px 10px;"
            " font-family: monospace; font-size: 12px;"
            " background: #5a2828; color: #ffd5d5; border: 1px solid #8a3a3a; }"
            " QPushButton:hover { background: #6a3030; }"
        )

        for idx, (start, end) in enumerate(self._ranges):
            chip = QPushButton(f"{_fmt_time(start)} → {_fmt_time(end)}  ×")
            chip.setCursor(Qt.PointingHandCursor)
            chip.setStyleSheet(chip_style)
            chip.setToolTip("Click to remove this range")
            chip.clicked.connect(lambda _checked=False, i=idx: self._remove_range(i))
            self._chip_layout.addWidget(chip)

        self._chip_layout.addStretch()

        pending = self._pending_start is not None
        self._btn_end.setEnabled(pending)
