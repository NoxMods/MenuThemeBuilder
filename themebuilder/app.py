import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from . import APP_NAME
from .ui.main_window import MainWindow


def dark_palette():
    p = QPalette()
    c = {
        QPalette.Window: "#23262b", QPalette.WindowText: "#e6e6e6", QPalette.Base: "#1a1c20",
        QPalette.AlternateBase: "#23262b", QPalette.ToolTipBase: "#2d3036", QPalette.ToolTipText: "#e6e6e6",
        QPalette.Text: "#e6e6e6", QPalette.Button: "#2f333a", QPalette.ButtonText: "#e6e6e6",
        QPalette.BrightText: "#ff5555", QPalette.Link: "#6cb4ff", QPalette.Highlight: "#3d7ad6",
        QPalette.HighlightedText: "#ffffff",
    }
    for role, col in c.items():
        p.setColor(role, QColor(col))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor("#777"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#777"))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#777"))
    return p


def run():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("MenuThemeBuilder")
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    w = MainWindow()
    w.show()
    return app.exec()
