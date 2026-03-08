DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #2b2b2b;
    color: #e0e0e0;
    font-size: 14px;
}

QGroupBox {
    border: 1px solid #555;
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 18px;
    font-weight: bold;
    font-size: 13px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}

QPushButton {
    background-color: #3c3c3c;
    border: 1px solid #555;
    border-radius: 4px;
    padding: 4px 14px;
    color: #e0e0e0;
    min-height: 24px;
    font-size: 13px;
}
QPushButton:hover { background-color: #4a4a4a; }
QPushButton:pressed { background-color: #555; }
QPushButton:disabled { color: #666; background-color: #333; }

QPushButton[primary="true"] {
    background-color: #2196F3;
    border-color: #1976D2;
    color: white;
    font-weight: bold;
    font-size: 15px;
    padding: 6px 24px;
    min-height: 28px;
}
QPushButton[primary="true"]:hover { background-color: #42A5F5; }
QPushButton[primary="true"]:disabled { background-color: #444; color: #777; }

QSlider {
    min-height: 28px;
}
QSlider::groove:horizontal {
    border: 1px solid #444;
    height: 8px;
    background: #1e1e1e;
    border-radius: 4px;
}
QSlider::handle:horizontal {
    background: #2196F3;
    border: none;
    width: 18px;
    margin: -6px 0;
    border-radius: 9px;
}
QSlider::handle:horizontal:hover {
    background: #42A5F5;
}

QDoubleSpinBox, QSpinBox, QComboBox, QLineEdit {
    background-color: #3c3c3c;
    border: 1px solid #555;
    border-radius: 3px;
    padding: 4px 6px;
    color: #e0e0e0;
    min-height: 24px;
    font-size: 13px;
}
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 20px;
    border-left: 1px solid #555;
    border-bottom: 1px solid #555;
    border-top-right-radius: 3px;
    background-color: #3c3c3c;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover {
    background-color: #4a4a4a;
}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed {
    background-color: #555;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 20px;
    border-left: 1px solid #555;
    border-top: 1px solid #555;
    border-bottom-right-radius: 3px;
    background-color: #3c3c3c;
}
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: #4a4a4a;
}
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {
    background-color: #555;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: none;
    width: 0;
    height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-bottom: 5px solid #e0e0e0;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: none;
    width: 0;
    height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 5px solid #e0e0e0;
}
QToolTip {
    background-color: #3c3c3c;
    color: #e0e0e0;
    border: 1px solid #555;
    padding: 4px 6px;
    font-size: 13px;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background-color: #3c3c3c;
    color: #e0e0e0;
    selection-background-color: #2196F3;
}

QListWidget {
    background-color: #1e1e1e;
    border: 1px solid #555;
    border-radius: 3px;
    padding: 2px;
}
QListWidget::item { padding: 3px 6px; }
QListWidget::item:selected { background-color: #2196F3; }

QProgressBar {
    border: 1px solid #555;
    border-radius: 4px;
    text-align: center;
    background-color: #1e1e1e;
    color: #e0e0e0;
    min-height: 24px;
}
QProgressBar::chunk {
    background-color: #2196F3;
    border-radius: 3px;
}

QTabWidget::pane {
    border: 1px solid #555;
    border-radius: 3px;
    padding: 4px;
}
QTabBar::tab {
    background-color: #333;
    border: 1px solid #555;
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    padding: 6px 16px;
    margin-right: 2px;
    color: #aaa;
    font-size: 13px;
}
QTabBar::tab:selected {
    background-color: #3c3c3c;
    color: #e0e0e0;
}

QCheckBox { spacing: 6px; font-size: 13px; }
QCheckBox::indicator { width: 18px; height: 18px; }

QRadioButton { spacing: 6px; font-size: 13px; }
QRadioButton::indicator { width: 18px; height: 18px; }
QRadioButton::indicator:unchecked {
    border: 2px solid #888; border-radius: 10px; background-color: #3c3c3c;
}
QRadioButton::indicator:checked {
    border: 2px solid #2196F3; border-radius: 10px; background-color: #2196F3;
}
QRadioButton::indicator:hover { border-color: #42A5F5; }

QSplitter::handle { background-color: #444; width: 2px; }
QScrollArea { border: none; }

QStatusBar { font-size: 12px; color: #aaa; }
"""
