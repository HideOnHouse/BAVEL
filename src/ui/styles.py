"""QSS stylesheets and theme definitions for BAVEL."""

DARK_THEME = """
QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: "Segoe UI", "Malgun Gothic", sans-serif;
    font-size: 10pt;
}

QMainWindow {
    background-color: #1e1e2e;
}

QLabel {
    color: #cdd6f4;
    padding: 2px;
}

QLabel#title-label {
    font-size: 16pt;
    font-weight: bold;
    color: #89b4fa;
}

QLabel#status-label {
    color: #a6adc8;
    font-size: 9pt;
}

QLabel#connected-label {
    color: #a6e3a1;
    font-weight: bold;
}

QLabel#disconnected-label {
    color: #f38ba8;
    font-weight: bold;
}

QComboBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 12px;
    min-height: 24px;
}

QComboBox:hover {
    border-color: #89b4fa;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox QAbstractItemView {
    background-color: #313244;
    color: #cdd6f4;
    selection-background-color: #45475a;
    border: 1px solid #585b70;
    border-radius: 4px;
}

QPushButton {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 8px 16px;
    min-height: 24px;
}

QPushButton:hover {
    background-color: #45475a;
    border-color: #89b4fa;
}

QPushButton:pressed {
    background-color: #585b70;
}

QPushButton#start-btn {
    background-color: #89b4fa;
    color: #1e1e2e;
    font-size: 12pt;
    font-weight: bold;
    border: none;
    border-radius: 8px;
    padding: 12px;
    min-height: 32px;
}

QPushButton#start-btn:hover {
    background-color: #74c7ec;
}

QPushButton#start-btn:pressed {
    background-color: #89dceb;
}

QPushButton#stop-btn {
    background-color: #f38ba8;
    color: #1e1e2e;
    font-size: 12pt;
    font-weight: bold;
    border: none;
    border-radius: 8px;
    padding: 12px;
    min-height: 32px;
}

QPushButton#stop-btn:hover {
    background-color: #eba0ac;
}

QPushButton#hotkey-btn {
    background-color: #313244;
    border: 1px dashed #585b70;
    font-family: "Consolas", monospace;
    font-size: 9pt;
    padding: 4px 8px;
}

QPushButton#hotkey-btn:hover {
    border-color: #f9e2af;
    color: #f9e2af;
}

QSlider::groove:horizontal {
    height: 6px;
    background: #313244;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #89b4fa;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}

QSlider::sub-page:horizontal {
    background: #89b4fa;
    border-radius: 3px;
}

QGroupBox {
    border: 1px solid #45475a;
    border-radius: 8px;
    margin-top: 12px;
    padding: 16px 8px 8px 8px;
    font-weight: bold;
    color: #bac2de;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}

QScrollArea {
    border: none;
    background-color: transparent;
}

QListWidget {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 4px;
}

QListWidget::item {
    padding: 6px;
    border-radius: 4px;
}

QListWidget::item:selected {
    background-color: #45475a;
    color: #89b4fa;
}

QListWidget::item:hover {
    background-color: #3b3d50;
}
"""

OVERLAY_STYLE = """
QWidget#overlay-container {
    background-color: rgba(17, 17, 27, 200);
    border-radius: 12px;
}

QLabel#subtitle-label {
    color: #cdd6f4;
    font-family: "Segoe UI", "Malgun Gothic", sans-serif;
    padding: 4px 8px;
}

QLabel#speaker-notification {
    background-color: rgba(137, 180, 250, 180);
    color: #1e1e2e;
    font-weight: bold;
    border-radius: 8px;
    padding: 6px 12px;
}
"""
