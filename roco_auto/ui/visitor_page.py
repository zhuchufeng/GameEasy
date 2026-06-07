"""Visitor page — per-stage YOLO models for "互访炫彩" two-window automation."""

import os, time, json

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QPushButton, QLabel, QDoubleSpinBox,
    QLineEdit, QScrollArea, QFrame, QMessageBox,
    QComboBox,
)
from PySide6.QtCore import Qt, QTimer, Signal

from roco_auto.core.visitor_engine import VisitorEngine, Stage, _STAGE_LABELS, _STAGE_COLORS
from roco_auto.core.config_manager import get_app_dir
from roco_auto.ui.region_selector import RegionSelector


# ═══════════════════════════════════════════  Floating window  ═══

class _VisitorFloatingWindow(QWidget):
    stop_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("互访炫彩运行中")
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setMinimumWidth(200)
        self.setStyleSheet("background:#1a1a2e; border-radius:8px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 6)
        layout.setSpacing(4)

        self._title_lbl = QLabel("互访炫彩"); self._title_lbl.setAlignment(Qt.AlignCenter)
        self._title_lbl.setStyleSheet("color:#6c8cff; font-size:13px; font-weight:bold; border:none; background:transparent;")
        layout.addWidget(self._title_lbl)

        self._stage_lbl = QLabel("就绪"); self._stage_lbl.setAlignment(Qt.AlignCenter)
        self._stage_lbl.setStyleSheet("color:#888; font-size:18px; font-weight:bold; padding:6px 0; border:none; background:transparent;")
        layout.addWidget(self._stage_lbl)

        self._detect_lbl = QLabel("等待检测..."); self._detect_lbl.setAlignment(Qt.AlignCenter)
        self._detect_lbl.setStyleSheet("color:#666; font-size:11px; border:none; background:transparent;")
        layout.addWidget(self._detect_lbl)

        bar = QWidget(); bar.setStyleSheet("background:transparent;")
        bl = QHBoxLayout(bar); bl.setContentsMargins(0, 4, 0, 0); bl.setSpacing(4)
        self._stat_lbl = QLabel("第 0 轮 | 00:00")
        self._stat_lbl.setStyleSheet("color:#777; font-size:10px; border:none; background:transparent;")
        bl.addWidget(self._stat_lbl); bl.addStretch()
        stop_btn = QPushButton("停止"); stop_btn.setCursor(Qt.PointingHandCursor); stop_btn.setFixedSize(40, 22)
        stop_btn.setStyleSheet("QPushButton{font-size:11px;font-weight:bold;border:none;border-radius:3px;background:#ff5c5c;color:#fff;}QPushButton:hover{background:#ee4444;}")
        stop_btn.clicked.connect(self.stop_requested.emit)
        bl.addWidget(stop_btn)
        layout.addWidget(bar)
        self._drag_pos = None

    def set_stage(self, name: str):
        color = _STAGE_COLORS.get(name, "#888")
        self._stage_lbl.setText(name)
        self._stage_lbl.setStyleSheet(f"color:{color}; font-size:18px; font-weight:bold; padding:6px 0; border:none; background:transparent;")

    def set_detect_status(self, text: str, found: bool = False):
        color = "#4ade80" if found else "#ce9178"
        self._detect_lbl.setText(text)
        self._detect_lbl.setStyleSheet(f"color:{color}; font-size:11px; border:none; background:transparent;")

    def set_stats(self, loop: int, elapsed_str: str):
        self._stat_lbl.setText(f"第 {loop} 轮 | {elapsed_str}")

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


# ═══════════════════════════════════════════  Main Page  ═══

class VisitorPage(QWidget):
    STAGE_MODELS = [
        ("enter",  "进入访问"),
        ("request","申请访问"),
        ("accept", "同意访问"),
        ("world",  "世界人数"),
        ("exit",   "退出世界"),
    ]
    DEFAULT_MODEL_DIR = os.path.join(get_app_dir(), "models", "visitor")

    def __init__(self, auto, parent=None):
        super().__init__(parent)
        self._a = auto
        self._engine = VisitorEngine()
        self._engine.on_status = self._on_status
        self._engine.on_stage_change = self._on_stage
        self._engine.on_detected = self._on_detected

        self._main_window = None
        self._floating = None
        self._timers = []
        self._last_detect_text = ""
        self._last_detect_found = False
        self._model_widgets = {}  # key → {"path": QLineEdit, "status": QLabel}
        self._init_ui()
        self._restore_config()

        self._poll = QTimer(self, interval=500, timeout=self._update_stats)
        self._poll.start()
        self._timers.append(self._poll)

        # Load models in background to avoid UI freeze
        QTimer.singleShot(100, self._load_models_async)

    def set_active(self, active: bool):
        for t in self._timers:
            if active: t.start()
            else: t.stop()

    # ═══════════════════════════════  Config  ═══

    @property
    def _config(self):
        if not hasattr(self, '_fallback_cfg'):
            import os as _os
            from roco_auto.core.config_manager import ConfigManager
            self._fallback_cfg = ConfigManager(_os.path.join(get_app_dir(), "roco_auto", "data", "saved_config.json"))
        return self._fallback_cfg

    @property
    def _saved_config_data(self) -> dict:
        cfg = self._config
        return cfg._data if cfg else {}

    def _save_visitor_config(self, updates: dict):
        cfg = self._config
        if cfg: cfg.update(updates); cfg.save()

    def _load_models_async(self):
        """Load all models in background to avoid UI freeze."""
        from PySide6.QtCore import QThread, Signal as QSignal

        class ModelLoader(QThread):
            done = QSignal(dict, bool)
            def __init__(self, engine, model_dir, minimap_path):
                super().__init__()
                self._engine = engine
                self._model_dir = model_dir
                self._minimap_path = minimap_path
            def run(self):
                results = {}
                if os.path.isdir(self._model_dir):
                    results = self._engine.auto_load_models(self._model_dir)
                mm_ok = False
                if os.path.exists(self._minimap_path):
                    mm_ok = self._engine.load_minimap_model(self._minimap_path)
                self.done.emit(results, mm_ok)

        mm_default = os.path.join(get_app_dir(), "models", "colorful.onnx")
        self._loader = ModelLoader(self._engine, self.DEFAULT_MODEL_DIR, mm_default)
        self._loader.done.connect(self._on_models_loaded)
        self._loader.start()

    def _refresh_models(self):
        """Re-scan model directory and reload all models."""
        for w in self._model_widgets.values():
            w["status"].setText("加载中...")
            w["status"].setStyleSheet("color:#ce9178; font-size:11px;")
        self._load_models_async()

    def _on_models_loaded(self, results: dict, mm_ok: bool):
        """Update UI after models finish loading."""
        for key, w in self._model_widgets.items():
            if results.get(key):
                w["status"].setText("已加载")
                w["status"].setStyleSheet("color:#4ade80; font-size:11px;")
            else:
                w["status"].setText("未找到")
                w["status"].setStyleSheet("color:#ff5c5c; font-size:11px;")

        if mm_ok:
            self._mm_status.setText(f"已加载 ({', '.join(self._engine._minimap_classes)})")
            self._mm_status.setStyleSheet("color:#4ade80; font-size:11px;")

    def _restore_config(self):
        d = self._saved_config_data
        mm_classes = d.get("visitor_minimap_classes", ["PT", "HB"])
        self._minimap_classes_edit.setText(",".join(mm_classes))
        self._engine.set_minimap_classes(mm_classes)

        # Restore confidence
        conf = d.get("visitor_confidence", 0.7); self._yc.setValue(conf)
        ld = d.get("visitor_loop_delay", 0); self._loop_delay.setValue(ld); self._engine.set_loop_delay(ld)

        # Restore Server酱
        sckey = d.get("visitor_sckey", "")
        if sckey: self._sckey.setText(sckey)
        nt = d.get("visitor_notify_title", "")
        if nt: self._notify_title.setText(nt); self._engine.set_notify_title(nt)
        nb = d.get("visitor_notify_body", "")
        if nb: self._notify_body.setText(nb); self._engine.set_notify_body(nb)

        self._restore_crop()

    # ═══════════════════════════════  UI  ═══

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # Header
        header = QFrame()
        header.setObjectName("__vh__")
        header.setStyleSheet("QFrame#__vh__{border-bottom:1px solid #333; padding:8px 16px;}")
        hl = QVBoxLayout(header); hl.setContentsMargins(0, 0, 0, 4); hl.setSpacing(2)

        title_row = QHBoxLayout()
        lbl = QLabel("互访炫彩"); lbl.setStyleSheet("font-size:20px; font-weight:bold;")
        title_row.addWidget(lbl); title_row.addStretch()
        self._toggle_btn = self._make_toggle_btn("开始", self._toggle)
        title_row.addWidget(self._toggle_btn)
        hl.addLayout(title_row)

        stat_row = QHBoxLayout()
        self._stat_lbl = QLabel("等待开始..."); self._stat_lbl.setStyleSheet("font-weight:bold; font-size:12px;")
        stat_row.addWidget(self._stat_lbl); stat_row.addStretch()
        hl.addLayout(stat_row)

        self._stage_lbl = QLabel("就绪")
        self._stage_lbl.setStyleSheet("color:#6c8cff; font-size:13px; font-weight:bold; padding:2px 0;")
        hl.addWidget(self._stage_lbl)
        root.addWidget(header)

        # Scrollable content
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame); scroll.setStyleSheet("QScrollArea{border:none;}")
        content = QWidget(); cl = QVBoxLayout(content)
        cl.setContentsMargins(16, 10, 16, 10); cl.setSpacing(8)

        # Window 1
        g_win1 = QGroupBox("窗口1 (操作窗口)"); g_win1l = QGridLayout(g_win1); g_win1l.setSpacing(5)
        g_win1l.addWidget(QLabel("目标窗口:"), 0, 0)
        self._win1_combo = QComboBox(); self._win1_combo.setMinimumWidth(200)
        self._win1_combo.currentIndexChanged.connect(self._on_win1_selected)
        g_win1l.addWidget(self._win1_combo, 0, 1)
        btn_rf1 = QPushButton("刷新"); btn_rf1.clicked.connect(self._refresh_windows)
        g_win1l.addWidget(btn_rf1, 0, 2)
        cl.addWidget(g_win1)

        # Window 2
        g_win2 = QGroupBox("窗口2 (目标窗口)"); g_win2l = QGridLayout(g_win2); g_win2l.setSpacing(5)
        g_win2l.addWidget(QLabel("目标窗口:"), 0, 0)
        self._win2_combo = QComboBox(); self._win2_combo.setMinimumWidth(200)
        self._win2_combo.currentIndexChanged.connect(self._on_win2_selected)
        g_win2l.addWidget(self._win2_combo, 0, 1)
        btn_rf2 = QPushButton("刷新"); btn_rf2.clicked.connect(self._refresh_windows)
        g_win2l.addWidget(btn_rf2, 0, 2)
        cl.addWidget(g_win2)

        # Stage models (hidden — auto-loaded from default directory)
        for key, name in self.STAGE_MODELS:
            self._model_widgets[key] = {"status": QLabel("")}
        # Minimap model (hidden — auto-loaded)
        self._mm_status = QLabel("")
        # Minimap classes (hidden)
        self._minimap_classes_edit = QLineEdit("PT,HB")
        self._minimap_classes_edit.textChanged.connect(self._on_minimap_classes_changed)

        # Minimap region
        g_mm = QGroupBox("小地图检测区域 (在窗口2上框选)"); g_mml2 = QGridLayout(g_mm); g_mml2.setSpacing(5)
        self._crop_btn = QPushButton("框选小地图")
        self._crop_btn.setStyleSheet("QPushButton{font-weight:bold;padding:6px 12px;background:#6c8cff;color:#fff;border-radius:4px;}QPushButton:hover{background:#5a7aee;}")
        self._crop_btn.clicked.connect(self._open_region_selector)
        g_mml2.addWidget(self._crop_btn, 0, 0)
        self._crop_lbl = QLabel("未框选"); self._crop_lbl.setStyleSheet("color:#888; font-size:11px;")
        g_mml2.addWidget(self._crop_lbl, 0, 1)
        cl.addWidget(g_mm)

        # Server酱
        g_sc = QGroupBox("微信通知 (Server酱)"); g_scl = QGridLayout(g_sc); g_scl.setSpacing(5)
        g_scl.addWidget(QLabel("SendKey:"), 0, 0)
        self._sckey = QLineEdit(); self._sckey.setPlaceholderText("SCT123456...")
        self._sckey.setEchoMode(QLineEdit.Password)
        self._sckey.textChanged.connect(self._on_sckey_changed)
        g_scl.addWidget(self._sckey, 0, 1)
        g_scl.addWidget(QLabel("通知标题:"), 1, 0)
        self._notify_title = QLineEdit("互访炫彩检测通知")
        self._notify_title.textChanged.connect(self._on_notify_changed)
        g_scl.addWidget(self._notify_title, 1, 1)
        g_scl.addWidget(QLabel("通知内容:{name}=检测到的名字,{conf}=置信度,{time}=时间,{loop}=轮次"), 2, 0, 1, 2)
        self._notify_body = QLineEdit("检测到: {name}\n置信度: {conf:.3f}\n时间: {time}")
        self._notify_body.textChanged.connect(self._on_notify_changed)
        g_scl.addWidget(self._notify_body, 3, 0, 1, 2)
        cl.addWidget(g_sc)

        # Confidence
        g_conf = QGroupBox("通用设置"); g_confl = QGridLayout(g_conf); g_confl.setSpacing(5)
        g_confl.addWidget(QLabel("YOLO 置信度:"), 0, 0)
        self._yc = QDoubleSpinBox(); self._yc.setRange(0.10, 1.00); self._yc.setSingleStep(0.05)
        self._yc.setValue(0.7); self._yc.setDecimals(2)
        self._yc.valueChanged.connect(self._on_confidence_changed)
        g_confl.addWidget(self._yc, 0, 1)
        g_confl.addWidget(QLabel("轮次间隔(秒):"), 1, 0)
        self._loop_delay = QDoubleSpinBox(); self._loop_delay.setRange(0, 3600)
        self._loop_delay.setSingleStep(1); self._loop_delay.setDecimals(0)
        self._loop_delay.setValue(0); self._loop_delay.setSuffix(" 秒")
        self._loop_delay.setToolTip("完成一轮后等待的秒数，0=不等待直接下一轮")
        self._loop_delay.valueChanged.connect(self._on_loop_delay_changed)
        g_confl.addWidget(self._loop_delay, 1, 1)
        cl.addWidget(g_conf)

        cl.addStretch()
        scroll.setWidget(content); root.addWidget(scroll, 1)
        self._refresh_windows()

    # ═══════════════════════════════  Window selection  ═══

    def _refresh_windows(self):
        from roco_auto.core.window_finder import list_all_visible_windows
        ws = list_all_visible_windows()
        d = self._saved_config_data
        for combo, saved_title_key, handler in [
            (self._win1_combo, "visitor_win1_title", self._on_win1_selected),
            (self._win2_combo, "visitor_win2_title", self._on_win2_selected),
        ]:
            combo.blockSignals(True); combo.clear()
            combo.addItem("(未选择)", None)
            saved_title = d.get(saved_title_key, ""); matched_idx = -1
            for i, w in enumerate(ws):
                label = f"{w['title'][:35]}  ({w['width']}x{w['height']})"
                combo.addItem(label, (w["hwnd"], w["title"]))
                if w["title"] == saved_title and matched_idx < 0:
                    matched_idx = i + 1
            if matched_idx >= 0: combo.setCurrentIndex(matched_idx)
            combo.blockSignals(False); handler(combo.currentIndex())

    def _on_win1_selected(self, _i):
        data = self._win1_combo.currentData()
        if data is None: self._engine.set_win1(None); return
        hwnd, title = data
        self._engine.set_win1(hwnd)
        self._save_visitor_config({"visitor_win1_title": title})

    def _on_win2_selected(self, _i):
        data = self._win2_combo.currentData()
        if data is None: self._engine.set_win2(None); return
        hwnd, title = data
        self._engine.set_win2(hwnd)
        self._save_visitor_config({"visitor_win2_title": title})

    def _on_minimap_classes_changed(self, text):
        classes = [c.strip() for c in text.split(",") if c.strip()]
        self._engine.set_minimap_classes(classes)
        self._save_visitor_config({"visitor_minimap_classes": classes})

    def _on_loop_delay_changed(self, value):
        self._engine.set_loop_delay(value)
        self._save_visitor_config({"visitor_loop_delay": value})

    def _on_confidence_changed(self, value):
        self._engine.set_confidence(value)
        self._save_visitor_config({"visitor_confidence": value})

    def _on_sckey_changed(self, text):
        self._engine.set_sckey(text)
        self._save_visitor_config({"visitor_sckey": text})

    def _on_notify_changed(self):
        self._engine.set_notify_title(self._notify_title.text())
        self._engine.set_notify_body(self._notify_body.text())
        self._save_visitor_config({
            "visitor_notify_title": self._notify_title.text(),
            "visitor_notify_body": self._notify_body.text(),
        })

    # ═══════════════════════════════  Minimap region  ═══

    def _open_region_selector(self):
        rect = self._engine._get_window_rect(self._engine._win2_hwnd)
        if not rect:
            QMessageBox.warning(self, "提示", "请先在窗口2中选择游戏窗口"); return
        self._overlay = RegionSelector(rect)
        self._overlay.region_confirmed.connect(self._on_region_selected); self._overlay.show()

    def _on_region_selected(self, rx1, ry1, rxx, ryy):
        rect = self._engine._get_window_rect(self._engine._win2_hwnd)
        if rect: self._engine.set_minimap_region_from_window(rect, rx1, ry1, rxx, ryy)
        self._crop_lbl.setText(f"已框选: ({rx1:.3f},{ry1:.3f})-({rxx:.3f},{ryy:.3f})")
        self._crop_lbl.setStyleSheet("color:#4ade80; font-size:11px;")
        self._save_crop(rx1, ry1, rxx, ryy)

    def _restore_crop(self):
        d = self._saved_config_data
        crop = d.get("visitor_crop")
        if crop and len(crop) == 4:
            self._crop_lbl.setText(f"已恢复: ({crop[0]:.3f},{crop[1]:.3f})-({crop[2]:.3f},{crop[3]:.3f})")
            self._crop_lbl.setStyleSheet("color:#4ade80; font-size:11px;")

    def _save_crop(self, rx1, ry1, rxx, ryy):
        self._save_visitor_config({"visitor_crop": [rx1, ry1, rxx, ryy]})

    # ═══════════════════════════════  Callbacks  ═══

    def _on_status(self, text):
        self._stat_lbl.setText(text)
        self._last_detect_text = text
        self._last_detect_found = "检测到" in text

    def _on_stage(self, name):
        self._stage_lbl.setText(f"当前阶段: {name}")
        self._stage_lbl.setStyleSheet(f"color:{_STAGE_COLORS.get(name, '#fff')}; font-size:13px; font-weight:bold; padding:2px 0;")
        if self._floating: self._floating.set_stage(name)

    def _on_detected(self, name, score):
        self._stat_lbl.setText(f"检测到: {name} ({score:.3f}) — 已发微信通知")
        self._last_detect_text = f"检测到: {name} ({score:.3f})"
        self._last_detect_found = True

    def _update_stats(self):
        e = self._engine
        if e.running:
            elapsed = time.time() - e.start_time
            m, s = divmod(int(elapsed), 60)
            stage_name = _STAGE_LABELS.get(e.stage, str(e.stage))
            self._stat_lbl.setText(f"第 {e.loop_count} 轮 | {m:02d}:{s:02d} | 阶段: {stage_name}")
            if self._floating:
                self._floating.set_stats(e.loop_count, f"{m:02d}:{s:02d}")
                self._floating.set_detect_status(self._last_detect_text, self._last_detect_found)

    # ═══════════════════════════════  Control  ═══

    def _toggle(self):
        if self._engine.running:
            self._engine.stop()
            if self._floating: self._floating.close(); self._floating = None
            mw = self._get_main_window()
            if mw: mw.show()
            return

        if self._engine._win1_hwnd is None:
            QMessageBox.warning(self, "错误", "请先选择窗口1"); return
        if self._engine._win2_hwnd is None:
            QMessageBox.warning(self, "错误", "请先选择窗口2"); return
        if not self._engine.yolo_loaded:
            QMessageBox.warning(self, "错误", "请加载全部5个阶段模型"); return
        if self._engine._minimap_region is None:
            QMessageBox.warning(self, "错误", "请先框选小地图区域"); return

        self._engine._input_backend = self._a._backend
        self._last_detect_text = "等待检测..."
        self._last_detect_found = False
        self._engine.start()
        self._show_floating()
        # Hide main window (not minimize) so it's excluded from Alt+Tab
        mw = self._get_main_window()
        if mw: mw.hide()

    def _get_main_window(self):
        if self._main_window is None: self._main_window = self.window()
        return self._main_window

    def _show_floating(self):
        self._floating = _VisitorFloatingWindow()
        self._floating.stop_requested.connect(self._stop_from_floating)
        screen = self.screen().availableGeometry()
        fw = self._floating; fw.adjustSize()
        fw.move(screen.right() - fw.width() - 20, screen.top() + 60)
        fw.show()

    def _stop_from_floating(self):
        self._engine.stop()
        if self._floating: self._floating.close(); self._floating = None
        mw = self._get_main_window()
        if mw: mw.show(); mw.raise_(); mw.activateWindow()

    def stop_all(self):
        if self._engine.running: self._engine.stop()
        if self._floating: self._floating.close(); self._floating = None
        mw = self._get_main_window()
        if mw: mw.show()

    def _make_toggle_btn(self, start_label, toggle_fn):
        btn = QPushButton(start_label); btn.setObjectName("__v_toggle__")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("QPushButton#__v_toggle__{font-size:14px;font-weight:bold;padding:10px 28px;border:none;border-radius:8px;background:#6c8cff;color:#fff;}QPushButton#__v_toggle__:hover{background:#5a7aee;}")
        def _upd():
            if self._engine.running:
                btn.setText("停止")
                btn.setStyleSheet("QPushButton#__v_toggle__{font-size:14px;font-weight:bold;padding:10px 28px;border:none;border-radius:8px;background:#ff5c5c;color:#fff;}")
            else:
                btn.setText(start_label)
                btn.setStyleSheet("QPushButton#__v_toggle__{font-size:14px;font-weight:bold;padding:10px 28px;border:none;border-radius:8px;background:#6c8cff;color:#fff;}QPushButton#__v_toggle__:hover{background:#5a7aee;}")
        t = QTimer(btn); t.timeout.connect(_upd); t.start(300)
        btn.clicked.connect(toggle_fn)
        return btn
