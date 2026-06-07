"""Application bootstrap and main entry point."""

import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from roco_auto.ui.main_window import MainWindow


def main() -> int:
    # High DPI scaling for 2K/4K screens
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("洛克王国减负小助手")
    app.setOrganizationName("RocoAuto")

    window = MainWindow()
    window.show()

    return app.exec()
