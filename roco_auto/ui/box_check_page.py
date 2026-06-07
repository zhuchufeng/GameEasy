"""BoxCheck page — YOLO-based chest detection with floating mini-window."""

import os, time, json
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QPushButton, QLabel, QSpinBox, QDoubleSpinBox,
    QCheckBox, QLineEdit, QFileDialog, QScrollArea, QFrame,
    QMessageBox, QComboBox,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QPixmap, QImage

from roco_auto.core.box_check import BoxCheckEngine
from roco_auto.core.config_manager import get_app_dir
from roco_auto.ui.region_selector import RegionSelector


class _BoxCheckBridge(QObject):
    status_signal = Signal(str)
    result_signal = Signal(object, str)
    detected_signal = Signal(str, float)


class _FloatingWindow(QWidget):
    """Small stay-on-top window showing detection results and a stop button."""

    stop_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("宝箱检测中")
        self.setWindowFlags(
            Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        self.setStyleSheet("background:#000;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._result_label = QLabel("等待捕获...")
        self._result_label.setAlignment(Qt.AlignCenter)
        self._result_label.setStyleSheet("color:#666; font-size:12px; background:#000; border:none;")
        layout.addWidget(self._result_label, 1)

        # Slim bottom bar
        bar = QWidget()
        bar.setFixedHeight(28)
        bar.setStyleSheet("background:rgba(0,0,0,180);")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(4, 2, 4, 2)
        bl.setSpacing(4)
        self._status_lbl = QLabel("监测中")
        self._status_lbl.setStyleSheet("color:#aaa; font-size:10px; border:none; background:transparent;")
        bl.addWidget(self._status_lbl)
        bl.addStretch()
        stop_btn = QPushButton("停止")
        stop_btn.setCursor(Qt.PointingHandCursor)
        stop_btn.setFixedSize(44, 22)
        stop_btn.setStyleSheet(
            "QPushButton { font-size:11px; font-weight:bold; border:none; border-radius:3px; background:#ff5c5c; color:#fff; }"
            "QPushButton:hover { background:#ee4444; }"
        )
        stop_btn.clicked.connect(self.stop_requested.emit)
        self._stat_lbl = QLabel("0张")
        self._stat_lbl.setStyleSheet("color:#777; font-size:10px; border:none; background:transparent;")
        bl.addWidget(self._stat_lbl)
        bl.addWidget(stop_btn)
        layout.addWidget(bar)
        self._stop_btn = stop_btn

        # Drag support
        self._drag_pos = None

    def update_result(self, pil_image):
        try:
            data = pil_image.tobytes("raw", "RGB")
            qimg = QImage(data, pil_image.width, pil_image.height,
                          pil_image.width * 3, QImage.Format_RGB888)
            pix = QPixmap.fromImage(qimg)
            iw, ih = pix.width(), pix.height()
            max_w, max_h = 500, 420
            if iw > max_w or ih > max_h:
                r = min(max_w / iw, max_h / ih)
                iw, ih = int(iw * r), int(ih * r)
                pix = pix.scaled(iw, ih, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._result_label.setPixmap(pix)
            self.resize(iw, ih + 28)
        except Exception:
            pass

    def update_status(self, text):
        if len(text) > 12:
            text = text[:10] + ".."
        self._status_lbl.setText(text)

    def update_stats(self, checks, elapsed_str, captures):
        self._stat_lbl.setText(f"{captures}张 | {elapsed_str}")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self._drag_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None


class BoxCheckPage(QWidget):
    def __init__(self, auto, parent=None):
        super().__init__(parent)
        self._a = auto
        self._engine = BoxCheckEngine()
        self._bridge = _BoxCheckBridge(self)
        self._main_window = None  # resolved on first show

        self._bridge.status_signal.connect(self._on_status)
        self._bridge.result_signal.connect(self._on_result)
        self._bridge.detected_signal.connect(self._on_detected)

        self._engine.on_status = self._bridge.status_signal.emit
        self._engine.on_result = self._bridge.result_signal.emit
        self._engine.on_detected = self._bridge.detected_signal.emit

        self._floating: _FloatingWindow | None = None
        self._results: list[dict] = []
        self._timers = []
        self._hotkey = ""  # global hotkey for box check toggle
        self._hk_buffer = []  # multi-key buffer
        self._hk_last = 0.0
        self._init_ui()

        # Register global hotkey for box check toggle
        from roco_auto.core.hotkey_manager import GlobalHotkeyManager
        GlobalHotkeyManager().register("boxcheck_hk", self._hotkey or "", self._toggle)

        self._poll = QTimer(self, interval=500, timeout=self._update_stats)
        self._poll.start()
        self._timers.append(self._poll)

    def set_active(self, active: bool):
        for t in self._timers:
            if active: t.start()
            else: t.stop()

    # ================================================================
    #  UI
    # ================================================================

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("__bc_header__")
        header.setStyleSheet("QFrame#__bc_header__ { border-bottom:1px solid #333; padding:8px 16px; }")
        hl = QVBoxLayout(header); hl.setContentsMargins(0, 0, 0, 4); hl.setSpacing(2)

        title_row = QHBoxLayout()
        lbl = QLabel("📦 宝箱检测")
        lbl.setStyleSheet("font-size:20px; font-weight:bold;")
        title_row.addWidget(lbl); title_row.addStretch()

        self._toggle_btn = self._make_toggle_btn("开始检测", self._toggle)
        title_row.addWidget(self._toggle_btn)
        hl.addLayout(title_row)

        stat_row = QHBoxLayout()
        self._stat_lbl = QLabel("0 次检测 | 00:00 | 0 次捕获")
        self._stat_lbl.setStyleSheet("font-weight:bold; font-size:12px;")
        stat_row.addWidget(self._stat_lbl); stat_row.addStretch()
        hl.addLayout(stat_row)

        self._status_lbl = QLabel("就绪 — 点击开始检测")
        self._status_lbl.setStyleSheet("padding:2px 0;")
        hl.addWidget(self._status_lbl)
        root.addWidget(header)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame); scroll.setStyleSheet("QScrollArea { border:none; }")
        content = QWidget(); cl = QVBoxLayout(content)
        cl.setContentsMargins(16, 10, 16, 10); cl.setSpacing(8)

        g1 = QGroupBox("检测设置"); g1l = QGridLayout(g1); g1l.setSpacing(5)

        g1l.addWidget(QLabel("模型:"), 0, 0)
        self._model_combo = QComboBox()
        self._model_combo.setToolTip("选择 YOLO 模型")
        self._refresh_models()
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)
        g1l.addWidget(self._model_combo, 0, 1)

        g1l.addWidget(QLabel("启停热键:"), 1, 0)
        from roco_auto.ui.hotkey_capture import HotkeyCapture
        self._hk_cap = HotkeyCapture("")
        self._hk_cap.setToolTip("设置全局启停热键，在任何页面都能用")
        self._hk_cap.key_changed.connect(lambda k: setattr(self, "_hotkey", k))
        g1l.addWidget(self._hk_cap, 1, 1)

        g1l.addWidget(QLabel("置信度:"), 2, 0)
        self._yc = QDoubleSpinBox(); self._yc.setRange(0.10, 1.00); self._yc.setSingleStep(0.05)
        self._yc.setValue(self._engine.yolo_confidence); self._yc.setDecimals(2)
        self._yc.valueChanged.connect(lambda v: setattr(self._engine, "yolo_confidence", v))
        g1l.addWidget(self._yc, 2, 1)

        g1l.addWidget(QLabel("截图区域:"), 3, 0)
        self._crop_btn = QPushButton("框选截图范围")
        self._crop_btn.setStyleSheet(
            "QPushButton { font-weight:bold; padding:6px 12px; background:#6c8cff; color:#fff; border-radius:4px; }"
            "QPushButton:hover { background:#5a7aee; }"
        )
        self._crop_btn.clicked.connect(self._open_crop_selector)
        g1l.addWidget(self._crop_btn, 3, 1)
        self._crop_lbl = QLabel("全屏 (未框选)")
        self._crop_lbl.setStyleSheet("color:#888; font-size:11px;")
        g1l.addWidget(self._crop_lbl, 4, 1)
        cl.addWidget(g1)

        g2 = QGroupBox("自动保存"); g2l = QHBoxLayout(g2); g2l.setSpacing(6)
        self._save_enabled = QCheckBox("启用")
        self._save_enabled.toggled.connect(self._toggle_save); g2l.addWidget(self._save_enabled)
        self._save_path = QLineEdit()
        default_save = os.path.join(get_app_dir(), "screenshots", "boxcheck")
        self._save_path.setText(os.path.abspath(default_save))
        self._save_path.setReadOnly(True); g2l.addWidget(self._save_path, 1)
        sb = QPushButton("浏览"); sb.clicked.connect(self._browse_save_path)
        g2l.addWidget(sb); cl.addWidget(g2)

        gr = QGroupBox("检测结果"); grl = QVBoxLayout(gr)
        grl.setContentsMargins(4, 4, 4, 4); grl.setSpacing(4)
        self._result_title = QLabel("等待中...")
        self._result_title.setStyleSheet("font-weight:bold; font-size:11px;"); grl.addWidget(self._result_title)
        self._result_scroll = QScrollArea(); self._result_scroll.setWidgetResizable(True)
        self._result_scroll.setMinimumHeight(200)
        self._result_label = QLabel("尚未捕获结果")
        self._result_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._result_label.setStyleSheet("padding:4px; background:#1e1e1e;")
        self._result_label.setMinimumHeight(150)
        self._result_label.setScaledContents(False)
        self._result_scroll.setWidget(self._result_label)
        grl.addWidget(self._result_scroll, 1); cl.addWidget(gr, 1)

        scroll.setWidget(content); root.addWidget(scroll, 1)

        # Load saved crop
        self._load_settings()

    # ================================================================
    #  Callbacks
    # ================================================================

    def _on_status(self, text: str):
        self._status_lbl.setText(text)
        if self._floating:
            self._floating.update_status(text)

    def _on_detected(self, name: str, score: float):
        self._status_lbl.setText(f"检测到: {name} (置信度: {score:.3f})")
        if self._floating:
            self._floating.update_status(f"检测到: {name} ({score:.3f})")

    def _on_result(self, pil_image, info: str):
        # Show in floating window
        if self._floating:
            self._floating.update_result(pil_image)

        # Also show in main page
        try:
            data = pil_image.tobytes("raw", "RGB")
            qimg = QImage(data, pil_image.width, pil_image.height,
                          pil_image.width * 3, QImage.Format_RGB888)
            pix = QPixmap.fromImage(qimg)
            scroll_w = self._result_scroll.viewport().width() - 10
            target_w = min(pix.width(), max(scroll_w, 300))
            scaled = pix.scaledToWidth(target_w, Qt.SmoothTransformation)
            self._result_label.setPixmap(scaled)
            self._result_label.setFixedSize(scaled.size())
            self._result_title.setText(f"检测结果 — {info}")
            self._results.append({"image": pil_image, "info": info, "time": datetime.now()})
            if len(self._results) > 20:
                self._results = self._results[-20:]
        except Exception:
            pass

    def _update_stats(self):
        e = self._engine
        elapsed = time.time() - e.start_time if e.is_running() and e.start_time > 0 else 0
        m, s = divmod(int(elapsed), 60)
        elapsed_str = f"{m:02d}:{s:02d}"
        self._stat_lbl.setText(f"{e.check_count} 次检测 | {elapsed_str} | {e.capture_count} 次捕获")
        if self._floating:
            self._floating.update_stats(e.check_count, elapsed_str, e.capture_count)

    def _on_hotkey(self, _name: str, combo: str) -> bool:
        """Global hotkey handler. Toggle box check from any app page."""
        import time
        now = time.time()
        if now - self._hk_last > 0.8:
            self._hk_buffer = []
        self._hk_buffer.append(combo)
        self._hk_last = now
        candidate = "+".join(self._hk_buffer)
        if self._hotkey and candidate == self._hotkey:
            self._hk_buffer = []
            self._toggle()
            return True
        return False

    # ================================================================
    #  Model selection
    # ================================================================

    def _refresh_models(self):
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        models_dir = os.path.join(get_app_dir(), "models")
        if os.path.isdir(models_dir):
            for f in sorted(os.listdir(models_dir)):
                if f.endswith(".onnx"):
                    self._model_combo.addItem(f, os.path.join(models_dir, f))
        self._model_combo.blockSignals(False)

    def _on_model_changed(self, idx):
        if idx < 0:
            return
        path = self._model_combo.itemData(idx)
        if path and os.path.exists(path):
            self._engine.load_yolo(path, self._yc.value())
            if self._engine.using_yolo:
                cls_str = ", ".join(self._engine.yolo_classes)
                self._status_lbl.setText(f"模型已加载: {cls_str}")
            else:
                self._status_lbl.setText("模型加载失败")

    # ================================================================
    #  Crop region
    # ================================================================

    def _open_crop_selector(self):
        win = self._a.get_target_window()
        if not win:
            QMessageBox.warning(self, "提示", "请先在顶部选择游戏窗口。")
            return
        self._crop_overlay = RegionSelector(win)
        self._crop_overlay.region_confirmed.connect(self._on_crop_selected)
        self._crop_overlay.show()

    def _on_crop_selected(self, rx1, ry1, rxx, ryy):
        self._engine.crop_rx1 = rx1
        self._engine.crop_ry1 = ry1
        self._engine.crop_rx2 = rxx
        self._engine.crop_ry2 = ryy
        self._crop_lbl.setText(f"已框选: ({rx1:.3f},{ry1:.3f})→({rxx:.3f},{ryy:.3f})")
        self._crop_lbl.setStyleSheet("color:#4ade80; font-size:11px;")

    # ================================================================
    #  Control
    # ================================================================

    def is_running(self) -> bool:
        return self._engine.is_running()

    def _toggle(self):
        if self._engine.is_running():
            self._stop_detection()
            return

        # Load selected model if not loaded
        if not self._engine.using_yolo:
            idx = self._model_combo.currentIndex()
            if idx >= 0:
                path = self._model_combo.itemData(idx)
                if path:
                    self._engine.load_yolo(path, self._yc.value())
        if not self._engine.using_yolo:
            QMessageBox.warning(self, "错误", "请先选择一个 YOLO 模型")
            return
        win = self._a.get_target_window()
        if not win:
            QMessageBox.warning(self, "错误", "请先在顶部选择游戏窗口")
            return
        if self._save_enabled.isChecked():
            self._engine.save_to_folder = self._save_path.text()
        else:
            self._engine.save_to_folder = ""
        self._engine.start()

        # Show floating mini-window, minimize main window
        self._show_floating()

    def _get_main_window(self):
        if self._main_window is None:
            self._main_window = self.window()
        return self._main_window

    def _show_floating(self):
        self._floating = _FloatingWindow()
        self._floating.stop_requested.connect(self._stop_detection)

        # Restore saved position or use default
        screen = self.screen().availableGeometry()
        default_x = screen.right() - 380
        default_y = screen.bottom() - 340
        try:
            pos = self._load_float_pos()
            if pos:
                default_x, default_y = pos
        except Exception:
            pass
        self._floating.move(default_x, default_y)
        self._floating.show()
        # Size to initial content
        self._floating.adjustSize()

        mw = self._get_main_window()
        if mw:
            mw.showMinimized()

    def _stop_detection(self):
        self._engine.stop()

        if self._floating:
            # Save window position
            geo = self._floating.geometry()
            self._save_float_pos(geo.x(), geo.y())
            self._floating.close()
            self._floating = None

        mw = self._get_main_window()
        if mw:
            mw.showNormal()
            mw.raise_()
            mw.activateWindow()

    def stop_all(self):
        self._stop_detection()

    # ================================================================
    #  Save
    # ================================================================

    def _toggle_save(self, enabled: bool):
        path = self._save_path.text()
        self._engine.save_to_folder = path if enabled else ""

    def _browse_save_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择保存目录")
        if path:
            self._save_path.setText(path)
            if self._save_enabled.isChecked():
                self._engine.save_to_folder = path

    def _float_pos_file(self) -> str:
        return os.path.join(get_app_dir(), "roco_auto", "data", "saved_config.json")

    def _save_float_pos(self, x, y):
        try:
            path = self._float_pos_file()
            data = {}
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data["boxcheck_float_x"] = x
            data["boxcheck_float_y"] = y
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_float_pos(self):
        path = self._float_pos_file()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            x = data.get("boxcheck_float_x")
            y = data.get("boxcheck_float_y")
            if x is not None and y is not None:
                return (x, y)
        return None

    def save_settings(self, config_manager=None):
        if config_manager is not None:
            config_manager.update({
                "boxcheck_crop": [self._engine.crop_rx1, self._engine.crop_ry1,
                                  self._engine.crop_rx2, self._engine.crop_ry2],
            })
            config_manager.save()

    def _load_settings(self):
        try:
            path = os.path.abspath(os.path.join(get_app_dir(), "roco_auto", "data", "saved_config.json"))
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                crop = data.get("boxcheck_crop")
                if crop and len(crop) == 4:
                    self._engine.crop_rx1, self._engine.crop_ry1, self._engine.crop_rx2, self._engine.crop_ry2 = crop
                    self._crop_lbl.setText(f"已加载: ({crop[0]:.3f},{crop[1]:.3f})-({crop[2]:.3f},{crop[3]:.3f})")
                    self._crop_lbl.setStyleSheet("color:#4ade80; font-size:11px;")
        except Exception:
            pass

    # ================================================================
    #  Helpers
    # ================================================================

    def _make_toggle_btn(self, start_label: str, toggle_fn):
        btn = QPushButton(start_label)
        btn.setObjectName("__bc_toggle__")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton#__bc_toggle__ { font-size:14px; font-weight:bold; padding:10px 28px;"
            " border:none; border-radius:8px; background:#6c8cff; color:#fff; }"
            "QPushButton#__bc_toggle__:hover { background:#5a7aee; }")

        def _upd():
            if self._engine.is_running():
                btn.setText("停止")
                btn.setStyleSheet(
                    "QPushButton#__bc_toggle__ { font-size:14px; font-weight:bold; padding:10px 28px;"
                    " border:none; border-radius:8px; background:#ff5c5c; color:#fff; }")
            else:
                btn.setText(start_label)
                btn.setStyleSheet(
                    "QPushButton#__bc_toggle__ { font-size:14px; font-weight:bold; padding:10px 28px;"
                    " border:none; border-radius:8px; background:#6c8cff; color:#fff; }"
                    "QPushButton#__bc_toggle__:hover { background:#5a7aee; }")

        t = QTimer(btn); t.timeout.connect(_upd); t.start(300)
        btn.clicked.connect(toggle_fn)
        return btn
