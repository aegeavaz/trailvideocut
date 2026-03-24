from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
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
    start_export = Signal(str, bool, bool)  # output_path, is_davinci, blur_plates

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_video_dir: Path | None = None
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
        mp4_desc = QLabel("Encode a standalone MP4 video file with audio using FFmpeg")
        mp4_desc.setStyleSheet("color: #888; font-size: 11px; margin-left: 22px;")
        self._radio_davinci = QRadioButton("DaVinci Resolve OTIO")
        otio_desc = QLabel("Export an OpenTimelineIO project for editing in DaVinci Resolve")
        otio_desc.setStyleSheet("color: #888; font-size: 11px; margin-left: 22px;")
        format_layout.addWidget(self._radio_video)
        format_layout.addWidget(mp4_desc)
        format_layout.addWidget(self._radio_davinci)
        format_layout.addWidget(otio_desc)

        self._chk_blur = QCheckBox("Blur license plates")
        blur_desc = QLabel(
            "Detect and blur plate numbers in the output video"
            " (requires trailvideocut[blur])"
        )
        blur_desc.setStyleSheet("color: #888; font-size: 11px; margin-left: 22px;")
        format_layout.addWidget(self._chk_blur)
        format_layout.addWidget(blur_desc)

        self._radio_davinci.toggled.connect(self._on_format_toggled)

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
            initial = self._output_path.text().strip() or "project.otio"
            path, _ = QFileDialog.getSaveFileName(
                self, "Save OTIO As", initial,
                "OpenTimelineIO (*.otio);;All Files (*)",
            )
        else:
            initial = self._output_path.text().strip() or "output.mp4"
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Video As", initial,
                "MP4 Video (*.mp4);;All Files (*)",
            )
        if path:
            self._output_path.setText(path)

    def _on_format_toggled(self):
        self._update_output_for_format()
        is_davinci = self._radio_davinci.isChecked()
        self._chk_blur.setEnabled(not is_davinci)
        if is_davinci:
            self._chk_blur.setChecked(False)

    def _on_start(self):
        output = self._output_path.text().strip()
        if not output:
            self._status_label.setText("Please select an output path.")
            return
        is_davinci = self._radio_davinci.isChecked()
        if not is_davinci:
            from trailvideocut.gpu import _find_ffmpeg
            if _find_ffmpeg() is None:
                self.set_error(
                    "FFmpeg not found. Install FFmpeg and add it to your system PATH.\n"
                    "Download: https://ffmpeg.org/download.html"
                )
                return
        blur_plates = self._chk_blur.isChecked() and not is_davinci
        self._btn_start.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._status_label.setText("Starting export...")
        self.start_export.emit(output, is_davinci, blur_plates)

    def set_default_output(self, video_path: Path):
        """Set default output path based on the video file location."""
        self._source_video_dir = video_path.parent
        self._update_output_for_format()

    def _update_output_for_format(self):
        """Update the output path field to match the selected export format."""
        if self._source_video_dir is None:
            return
        if self._radio_davinci.isChecked():
            self._output_path.setText(str(self._source_video_dir / "project.otio"))
        else:
            self._output_path.setText(str(self._source_video_dir / "output.mp4"))

    def set_progress(self, current: int, total: int):
        """Update progress bar with real encoding progress."""
        self._progress_bar.setRange(0, total)
        self._progress_bar.setValue(current)

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
        self._progress_bar.setRange(0, 0)  # reset to indeterminate
        self._progress_bar.setVisible(False)
        self._btn_start.setEnabled(True)
