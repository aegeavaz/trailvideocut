from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)


class ExportPage(QWidget):
    """Page 3: Export format, output path, and render progress."""

    back_requested = Signal()
    start_export = Signal(str, bool)  # output_path, is_davinci

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(12)

        # Navigation
        nav = QHBoxLayout()
        btn_back = QPushButton("<< Back to Review")
        btn_back.clicked.connect(self.back_requested.emit)
        nav.addWidget(btn_back)
        nav.addStretch()
        root.addLayout(nav)

        # Format selection
        format_group = QGroupBox("Export Format")
        format_layout = QVBoxLayout(format_group)

        self._radio_video = QRadioButton("Render Video (MP4)")
        self._radio_video.setChecked(True)
        self._radio_davinci = QRadioButton("DaVinci Resolve OTIO")
        format_layout.addWidget(self._radio_video)
        format_layout.addWidget(self._radio_davinci)

        root.addWidget(format_group)

        # Output path
        output_group = QGroupBox("Output")
        output_layout = QHBoxLayout(output_group)

        self._output_path = QLineEdit()
        self._output_path.setPlaceholderText("Select output location...")
        btn_browse = QPushButton("Browse")
        btn_browse.setFixedWidth(70)
        btn_browse.clicked.connect(self._browse_output)
        output_layout.addWidget(self._output_path)
        output_layout.addWidget(btn_browse)

        root.addWidget(output_group)

        # Start button
        self._btn_start = QPushButton("Start Export")
        self._btn_start.setProperty("primary", True)
        self._btn_start.clicked.connect(self._on_start)
        root.addWidget(self._btn_start, alignment=Qt.AlignCenter)

        # Progress
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_group)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)  # indeterminate
        self._progress_bar.setVisible(False)
        progress_layout.addWidget(self._progress_bar)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #aaa; padding: 4px;")
        progress_layout.addWidget(self._status_label)

        root.addWidget(progress_group)
        root.addStretch()

    def _browse_output(self):
        if self._radio_davinci.isChecked():
            path = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        else:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Video As", "output.mp4",
                "MP4 Video (*.mp4);;All Files (*)",
            )
        if path:
            self._output_path.setText(path)

    def _on_start(self):
        output = self._output_path.text().strip()
        if not output:
            self._status_label.setText("Please select an output path.")
            return
        is_davinci = self._radio_davinci.isChecked()
        self._btn_start.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._status_label.setText("Starting export...")
        self.start_export.emit(output, is_davinci)

    def set_default_output(self, video_path: Path):
        """Set default output path based on the video file location."""
        parent = video_path.parent
        self._output_path.setText(str(parent / "output.mp4"))

    def set_status(self, message: str):
        self._status_label.setText(message)

    def set_finished(self, output_path: str):
        self._progress_bar.setVisible(False)
        self._btn_start.setEnabled(True)
        self._status_label.setText(f"Export complete: {output_path}")
        self._status_label.setStyleSheet("color: #4CAF50; padding: 4px; font-weight: bold;")

    def set_error(self, message: str):
        self._progress_bar.setVisible(False)
        self._btn_start.setEnabled(True)
        self._status_label.setText(f"Error: {message}")
        self._status_label.setStyleSheet("color: #f44336; padding: 4px;")

    def reset_status(self):
        self._status_label.setText("")
        self._status_label.setStyleSheet("color: #aaa; padding: 4px;")
        self._progress_bar.setVisible(False)
        self._btn_start.setEnabled(True)
