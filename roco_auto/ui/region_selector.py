"""Live overlay for selecting a monitoring region directly on the game window."""

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRect, QPoint, Signal
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QFont


class RegionSelector(QWidget):
    """Semi-transparent overlay that sits on top of the game window.

    User drags a rectangle directly on the live game画面.  Press Enter
    to confirm, Esc to cancel.
    """

    region_confirmed = Signal(float, float, float, float)  # rx1, ry1, rx2, ry2

    def __init__(self, game_rect: dict):
        super().__init__()
        self._game_left = game_rect["left"]
        self._game_top = game_rect["top"]
        self._game_w = game_rect["width"]
        self._game_h = game_rect["height"]

        self._start = QPoint()
        self._end = QPoint()
        self._drawing = False
        self._rect: QRect | None = None

        # Frameless, transparent, stay-on-top
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(self._game_left, self._game_top, self._game_w, self._game_h)
        self.setCursor(Qt.CrossCursor)

        # Instruction label via paint
        self._help_text = "拖动鼠标框选监测区域 → Enter 确认 → Esc 取消"

    def paintEvent(self, event):
        painter = QPainter(self)

        # Dim overlay
        painter.setBrush(QBrush(QColor(0, 0, 0, 80)))
        painter.setPen(Qt.NoPen)
        painter.drawRect(self.rect())

        if self._rect is not None and self._rect.isValid():
            # Clear the selected area (show game through it)
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.drawRect(self._rect)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

            # Draw selection border
            pen = QPen(QColor("#6c8cff"), 2, Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self._rect)

            # Draw size label
            r = self._rect
            label = f"{r.width()} x {r.height()}"
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(0, 0, 0, 180)))
            label_rect = QRect(r.left() + 4, r.top() + 4, 120, 22)
            painter.drawRect(label_rect)
            painter.setPen(QColor("#fff"))
            painter.setFont(QFont("Microsoft YaHei", 10))
            painter.drawText(label_rect, Qt.AlignCenter, label)

        # Help text at bottom
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 160)))
        help_w = 420
        help_rect = QRect(
            (self._game_w - help_w) // 2, self._game_h - 36, help_w, 28
        )
        painter.drawRoundedRect(help_rect, 6, 6)
        painter.setPen(QColor("#ccc"))
        painter.setFont(QFont("Microsoft YaHei", 10))
        painter.drawText(help_rect, Qt.AlignCenter, self._help_text)

        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._start = event.pos()
            self._end = event.pos()
            self._drawing = True

    def mouseMoveEvent(self, event):
        if self._drawing:
            self._end = event.pos()
            self._update_rect()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._end = event.pos()
            self._drawing = False
            self._update_rect()

    def _update_rect(self):
        x1 = min(self._start.x(), self._end.x())
        y1 = min(self._start.y(), self._end.y())
        x2 = max(self._start.x(), self._end.x())
        y2 = max(self._start.y(), self._end.y())
        self._rect = QRect(x1, y1, x2 - x1, y2 - y1)
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            self._confirm()
        elif event.key() == Qt.Key_Escape:
            self.close()

    def _confirm(self):
        if self._rect is None or self._rect.width() < 10 or self._rect.height() < 10:
            return
        # Convert pixel coords (relative to game window) to ratios
        rx1 = self._rect.left() / self._game_w
        ry1 = self._rect.top() / self._game_h
        rx2 = self._rect.right() / self._game_w
        ry2 = self._rect.bottom() / self._game_h
        self.region_confirmed.emit(rx1, ry1, rx2, ry2)
        self.close()
