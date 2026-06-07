"""Main window — clean simple UI."""

import os, time
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFrame, QStackedWidget, QMessageBox, QComboBox,
    QSpinBox, QCheckBox,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence

from roco_auto.ui.serial_manager import SerialManagerWidget
from roco_auto.ui.game_page import (BattlePage, SkipPage, MinePage, ReleasePage, ThrowPage)
from roco_auto.ui.box_check_page import BoxCheckPage
from roco_auto.ui.visitor_page import VisitorPage
from roco_auto.core.game_automation import GameAutomation
from roco_auto.core.config_manager import ConfigManager, get_app_dir

# Common game window title keywords for auto-detection on first run
GAME_WINDOW_KEYWORDS = [
    "洛克王国",     # 洛克王国
    "Roco",
    "洛克",
    "王国",
]

SIDEBAR_WIDTH = 160

_DARK_QSS = """
    QMainWindow, QWidget { background:#1e1e2e; color:#e0e0e0;
        font-family:"Microsoft YaHei","Segoe UI",sans-serif; font-size:12px; }
    QGroupBox { border:1px solid #444; border-radius:6px; margin-top:10px;
        padding:12px 10px 8px 10px; font-weight:bold; color:#e0e0e0; }
    QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 6px; color:#6c8cff; }
    QPushButton { background:#3a3a50; color:#e0e0e0; border:1px solid #555;
        border-radius:4px; padding:5px 14px; font-size:12px; }
    QPushButton:hover { background:#4a4a65; border-color:#6c8cff; }
    QPushButton:pressed { background:#2a2a40; }
    QComboBox, QSpinBox, QDoubleSpinBox { background:#2a2a40; color:#e0e0e0;
        border:1px solid #555; border-radius:4px; padding:3px 20px 3px 8px; font-size:12px; }
    QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover { border-color:#6c8cff; }
    QComboBox::drop-down { border:none; width:20px; }
    QComboBox QAbstractItemView { background:#2a2a40; color:#e0e0e0;
        selection-background-color:#6c8cff; border:1px solid #555; }
    QSpinBox::up-button, QSpinBox::down-button { width:0; }
    QLabel { color:#d0d0d0; font-size:12px; }
    QCheckBox { spacing:8px; }
    QCheckBox::indicator { width:15px; height:15px; border:2px solid #666;
        border-radius:3px; background:#2a2a40; }
    QCheckBox::indicator:checked { background:#6c8cff; border-color:#6c8cff; }
    QSlider::groove:horizontal { border:1px solid #555; height:6px;
        background:#2a2a40; border-radius:3px; }
    QSlider::handle:horizontal { background:#6c8cff; width:14px;
        margin:-5px 0; border-radius:7px; }
    QSlider::sub-page:horizontal { background:#6c8cff; border-radius:3px; }
    QLineEdit, QTextEdit { background:#2a2a40; color:#e0e0e0;
        border:1px solid #555; border-radius:4px; padding:5px; }
    QScrollBar:vertical { background:#1e1e2e; width:8px; border-radius:4px; }
    QScrollBar::handle:vertical { background:#555; border-radius:4px; min-height:30px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
"""

_LIGHT_QSS = """
    QMainWindow, QWidget { background:#f5f5f5; color:#1a1a1a;
        font-family:"Microsoft YaHei","Segoe UI",sans-serif; font-size:12px; }
    QGroupBox { border:1px solid #d0d0d0; border-radius:6px; margin-top:10px;
        padding:12px 10px 8px 10px; font-weight:bold; color:#1a1a1a; background:#fff; }
    QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 6px;
        color:#5b6ce0; background:#fff; }
    QPushButton { background:#e8e8e8; color:#1a1a1a; border:1px solid #ccc;
        border-radius:4px; padding:5px 14px; font-size:12px; }
    QPushButton:hover { background:#d8e8f8; border-color:#5b6ce0; }
    QPushButton:pressed { background:#c0d8f0; }
    QComboBox, QSpinBox, QDoubleSpinBox { background:#fff; color:#1a1a1a;
        border:1px solid #ccc; border-radius:4px; padding:3px 20px 3px 8px; font-size:12px; }
    QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover { border-color:#5b6ce0; }
    QComboBox::drop-down { border:none; width:20px; }
    QComboBox QAbstractItemView { background:#fff; color:#1a1a1a;
        selection-background-color:#5b6ce0; border:1px solid #ccc; }
    QSpinBox::up-button, QSpinBox::down-button { width:0; }
    QLabel { color:#444; font-size:12px; }
    QCheckBox { spacing:8px; }
    QCheckBox::indicator { width:15px; height:15px; border:2px solid #bbb;
        border-radius:3px; background:#fff; }
    QCheckBox::indicator:checked { background:#5b6ce0; border-color:#5b6ce0; }
    QSlider::groove:horizontal { border:1px solid #ccc; height:6px;
        background:#e8e8e8; border-radius:3px; }
    QSlider::handle:horizontal { background:#5b6ce0; width:14px;
        margin:-5px 0; border-radius:7px; }
    QSlider::sub-page:horizontal { background:#5b6ce0; border-radius:3px; }
    QLineEdit, QTextEdit { background:#fff; color:#1a1a1a;
        border:1px solid #ccc; border-radius:4px; padding:5px; }
    QScrollBar:vertical { background:#f5f5f5; width:8px; border-radius:4px; }
    QScrollBar::handle:vertical { background:#bbb; border-radius:4px; min-height:30px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
"""


class MainWindow(QMainWindow):
    global_stopped = Signal()

    PAGES = [("战斗","battle"),("跳过剧情","skip"),("采矿切宠","mine"),
             ("放生","release"),("丢球","throw"),("开箱检测","boxcheck"),
             ("互访炫彩","visitor"),("串口","serial")]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("洛克王国减负小助手 v1.1")
        self.setMinimumSize(900,620); self.resize(960,680)
        self._is_dark = True
        self._auto = GameAutomation()
        self._config = ConfigManager(os.path.join(get_app_dir(), "roco_auto", "data", "saved_config.json"))
        self._load_saved_config()
        self._config.clean_stale_keys(self._get_known_config_keys())
        from roco_auto.core.hotkey_manager import GlobalHotkeyManager
        self._hotkey_mgr = GlobalHotkeyManager()
        self._hotkey_mgr.on_global_stop(self._emergency_stop)  # mouse X1 → stop
        self._setup_ui()
        self._register_hotkeys()
        # Re-register release page hotkeys (they were cleared by unregister_all)
        rp = self._pg.get("release")
        if rp and hasattr(rp, '_start_hk'):
            rp._start_hk()
        self._apply_theme()
        # Periodic auto-save every 60 seconds
        self._auto_save_timer = QTimer(self, interval=60000, timeout=self._periodic_save)
        self._auto_save_timer.start()

    def _load_saved_config(self):
        d = self._config.get_all(); a = self._auto
        for attr, key, default in [
            ("screen_w","screen_w",1920),("screen_h","screen_h",1080),
            ("battle_key","battle_key","1"),("battle_interval","battle_interval",3000),
            ("first_start_delay","first_start_delay",5000),
            ("skip_yolo_model","skip_yolo_model",""),("skip_confidence","skip_confidence",0.5),
            ("skip_poll_interval","skip_poll_interval",300),
            ("mine_switch_delay","mine_switch_delay",500),
            ("release_per_step","release_per_step",5),
            ("release_click_jitter","release_click_jitter",4),
            ("release_window_title","release_window_title","洛克王国"),
            ("release_all_pages","release_all_pages",False),
            ("throw_base_delay","throw_base_delay",1200),("throw_hold_time","throw_hold_time",300),
            ("throw_limit_enabled","throw_limit_enabled",False),
            ("throw_limit_count","throw_limit_count",50),
            ("throw_limit_action","throw_limit_action","stop"),
            ("throw_limit_wait_ms","throw_limit_wait_ms",5000),
            ("global_random_min","global_random_min",0),("global_random_max","global_random_max",500),
        ]: setattr(a, attr, d.get(key, default))
        for int_attr in ["release_x0","release_y0","release_x30","release_y30"]:
            setattr(a, int_attr, d.get(int_attr, 0))
        for rel_attr in ["release_confirm_rel","release_final_rel","release_next_page_rel"]:
            defaults = {"release_confirm_rel":[0.5,0.85],"release_final_rel":[0.5,0.88],
                        "release_next_page_rel":[0.9,0.92]}
            setattr(a, rel_attr, tuple(d.get(rel_attr, defaults[rel_attr])))
        for hk in ["hotkey_battle","hotkey_skip","hotkey_mine","hotkey_release","hotkey_throw"]:
            setattr(a, hk, d.get(hk,""))

    def _save_config(self):
        a = self._auto
        self._config.update({"screen_w":a.screen_w,"screen_h":a.screen_h,"battle_key":a.battle_key,
            "battle_interval":a.battle_interval,"first_start_delay":a.first_start_delay,
            "skip_yolo_model":a.skip_yolo_model,"skip_confidence":a.skip_confidence,
            "skip_poll_interval":a.skip_poll_interval,"mine_switch_delay":a.mine_switch_delay,
            "release_per_step":a.release_per_step,
            "release_x0":a.release_x0,"release_y0":a.release_y0,
            "release_x30":a.release_x30,"release_y30":a.release_y30,
            "release_confirm_rel":list(a.release_confirm_rel),
            "release_final_rel":list(a.release_final_rel),
            "release_next_page_rel":list(a.release_next_page_rel),
            "release_click_jitter":a.release_click_jitter,
            "release_window_title":a.release_window_title,"release_all_pages":a.release_all_pages,
            "throw_base_delay":a.throw_base_delay,"throw_hold_time":a.throw_hold_time,
            "throw_limit_enabled":a.throw_limit_enabled,"throw_limit_count":a.throw_limit_count,
            "throw_limit_action":a.throw_limit_action,"throw_limit_wait_ms":a.throw_limit_wait_ms,
            "hotkey_battle":a.hotkey_battle,"hotkey_skip":a.hotkey_skip,
            "hotkey_mine":a.hotkey_mine,"hotkey_release":a.hotkey_release,"hotkey_throw":a.hotkey_throw,
            "global_random_min":a.global_random_min,"global_random_max":a.global_random_max})
        # Also save boxcheck settings
        bc = self._pg.get("boxcheck")
        if bc is not None and hasattr(bc, "save_settings"):
            bc.save_settings(self._config)
        self._config.save()

    def _periodic_save(self):
        """Auto-save periodically to prevent data loss on crash."""
        try:
            self._save_config()
        except Exception:
            import logging
            logging.getLogger(__name__).warning("Periodic config save failed", exc_info=True)

    @staticmethod
    def _get_known_config_keys() -> set:
        """Return the set of config keys that are actually used."""
        from roco_auto.core.game_automation import KNOWN_CONFIG_KEYS
        return KNOWN_CONFIG_KEYS

    def _register_hotkeys(self):
        """Register/re-register all function hotkeys + customizable stop hotkey."""
        from roco_auto.core.hotkey_manager import GlobalHotkeyManager
        mgr = GlobalHotkeyManager()
        mgr.unregister_all()
        # Customizable global stop hotkey
        if self._stop_hk.key:
            mgr.register("global_stop", self._stop_hk.key, self._emergency_stop)
        a = self._auto

        for name, attr in [("battle","hotkey_battle"),("skip","hotkey_skip"),
                           ("mine","hotkey_mine"),("release","hotkey_release"),("throw","hotkey_throw")]:
            combo = getattr(a, attr, "")
            if combo:
                start_fn = {"battle":a.start_auto_battle,"skip":a.start_skip_story,
                      "mine":a.start_mine_listen,"release":a.start_release_pets,"throw":a.start_auto_throw}[name]
                def make_toggle(start_fn=start_fn, mode_name=name):
                    cn = {"battle":"自动战斗","skip":"跳过剧情","mine":"采矿切宠",
                          "release":"一键放生","throw":"自动丢球"}.get(mode_name, mode_name)
                    def toggle():
                        if a.is_running():
                            a.stop_all_safe()
                            self.global_stopped.emit()
                            self._slbl.setText(f"{cn} 已停止")
                        else:
                            start_fn()
                            self._slbl.setText(f"{cn} 已启动")
                    return toggle
                mgr.register(f"mode_{name}", combo, make_toggle())

        bc = self._pg.get("boxcheck")
        if bc and hasattr(bc, "_hotkey") and bc._hotkey:
            mgr.register("boxcheck", bc._hotkey, bc._toggle)

    def _emergency_stop(self):
        """Global stop: ONLY set stop flags, never touch Interception backend."""
        if not self._auto.is_running():
            bc = self._pg.get("boxcheck")
            vc = self._pg.get("visitor")
            if not (bc and bc.is_running()) and not (vc and vc._engine and vc._engine.running):
                return
        # Just set stop flags — let threads exit on their own
        self._auto.stop_all_safe()
        for key in ["boxcheck", "visitor"]:
            pg = self._pg.get(key)
            if pg and hasattr(pg, "_engine"):
                try: pg._engine._stop_flag = True
                except: pass
        self._slbl.setText("就绪")
        self._clbl.setText("")
        self.global_stopped.emit()

    def closeEvent(self, ev):
        self._auto.stop_all()
        # Also stop BoxCheck engine if running
        bc = self._pg.get("boxcheck")
        if bc is not None and hasattr(bc, "stop_all"):
            bc.stop_all()
        # Also stop Visitor engine if running
        vc = self._pg.get("visitor")
        if vc is not None and hasattr(vc, "stop_all"):
            vc.stop_all()
        self._save_config()
        self._hotkey_mgr.shutdown()
        ev.accept()

    def _setup_ui(self):
        c = QWidget(); self.setCentralWidget(c)
        r = QHBoxLayout(c); r.setContentsMargins(0,0,0,0); r.setSpacing(0)

        # Sidebar
        sb = QFrame(); sb.setFixedWidth(SIDEBAR_WIDTH); sb.setStyleSheet("background:#252540;")
        self._sidebar = sb
        sl = QVBoxLayout(sb); sl.setContentsMargins(0,10,0,10); sl.setSpacing(0)

        logo = QLabel("  洛克王国"); logo.setStyleSheet("font-size:15px; font-weight:bold; color:#6c8cff; padding:4px 0 2px 0;")
        sl.addWidget(logo)
        sub = QLabel("  减负小助手 v1.1"); sub.setStyleSheet("font-size:10px; color:#aaa; padding:0 0 14px 0;")
        sl.addWidget(sub)

        self._nav = []
        icons = {"battle":"⚔","skip":"⏭","mine":"⛏","release":"♻","throw":"⚾","boxcheck":"📦","visitor":"🤝","serial":"⚙"}
        for name, key in self.PAGES:
            btn = QPushButton(f"  {icons.get(key,'•')}   {name}")
            btn.setCheckable(True); btn.setCursor(Qt.PointingHandCursor); btn.setFixedHeight(40)
            btn.setStyleSheet("QPushButton{background:transparent;color:#b0b0d0;border:none;text-align:left;font-size:13px;padding-left:12px}"
                              "QPushButton:hover{background:#353560;color:#fff}"
                              "QPushButton:checked{background:#6c8cff33;color:#6c8cff;font-weight:bold;border-left:3px solid #6c8cff}")
            btn.clicked.connect(lambda checked,k=key: self._show_page(k))
            sl.addWidget(btn); self._nav.append((btn,key))

        sl.addStretch()

        tb = QPushButton("  ☀  亮色主题"); tb.setCursor(Qt.PointingHandCursor); tb.setFixedHeight(36)
        tb.setStyleSheet("QPushButton{background:#353560;color:#b0b0d0;border:none;border-radius:6px;margin:4px 8px;font-size:11px}"
                         "QPushButton:hover{color:#fff}")
        tb.clicked.connect(self._toggle_theme); self._theme_btn = tb; sl.addWidget(tb)
        r.addWidget(sb)

        # Right
        rw = QWidget(); rv = QVBoxLayout(rw); rv.setContentsMargins(0,0,0,0); rv.setSpacing(0)

        # Topbar
        top = QFrame(); top.setFixedHeight(44); top.setStyleSheet("background:#1a1a30; border-bottom:1px solid #333;")
        self._topbar = top
        tl = QHBoxLayout(top); tl.setContentsMargins(12,0,10,0)
        tl.addStretch()

        self._mode_sel = QComboBox()
        self._mode_sel.addItems(["内核驱动 (推荐)","Arduino (硬件)"])
        self._mode_sel.currentIndexChanged.connect(self._on_mode_changed)
        tl.addWidget(self._mode_sel)

        tl.addSpacing(6)
        self._win_combo = QComboBox(); self._win_combo.setMinimumWidth(180)
        self._win_combo.currentIndexChanged.connect(self._on_window_selected); tl.addWidget(self._win_combo)
        rf = QPushButton("⟳ 刷新"); rf.clicked.connect(self._refresh_window_list); tl.addWidget(rf)

        tl.addSpacing(8)
        tl.addWidget(QLabel("随机延迟:"))
        self._rmin = QSpinBox(); self._rmin.setRange(0,5000); self._rmin.setValue(self._auto.global_random_min); self._rmin.setFixedWidth(50)
        self._rmin.valueChanged.connect(lambda v: setattr(self._auto,"global_random_min",v)); tl.addWidget(self._rmin)
        tl.addWidget(QLabel("~"))
        self._rmax = QSpinBox(); self._rmax.setRange(0,5000); self._rmax.setValue(self._auto.global_random_max); self._rmax.setFixedWidth(50)
        self._rmax.valueChanged.connect(lambda v: setattr(self._auto,"global_random_max",v)); tl.addWidget(self._rmax)
        tl.addStretch()
        tl.addWidget(QLabel("全局停止:"))
        from roco_auto.ui.hotkey_capture import HotkeyCapture
        self._stop_hk = HotkeyCapture("F8")
        self._stop_hk.setToolTip("设置全局停止热键，在游戏中按下可停止所有功能")
        self._stop_hk.key_changed.connect(lambda k: self._register_hotkeys())
        tl.addWidget(self._stop_hk)
        tl.addSpacing(8)
        self._plbl = QLabel(""); tl.addWidget(self._plbl)
        rv.addWidget(top)

        # Pages
        self._stack = QStackedWidget(); self._pg = {}
        for name, key in self.PAGES:
            pg = self._make_page(key); self._pg[key] = pg; self._stack.addWidget(pg)
        self._show_page(self.PAGES[0][1]); rv.addWidget(self._stack,1)

        # Statusbar
        bar = QFrame(); bar.setFixedHeight(28); bar.setStyleSheet("background:#1a1a30; border-top:1px solid #333;")
        self._statusbar = bar
        bl = QHBoxLayout(bar); bl.setContentsMargins(12,0,10,0)
        self._slbl = QLabel("就绪"); bl.addWidget(self._slbl)
        bl.addStretch(); self._clbl = QLabel(""); bl.addWidget(self._clbl)
        rv.addWidget(bar)

        r.addWidget(rw,1)
        self._refresh_window_list(); self._wire_serial()
        self._on_mode_changed(0)  # 显式初始化内核驱动：必须在所有控件创建后调用

        # Keyboard shortcuts
        for i, (_name, key) in enumerate(self.PAGES):
            action = QAction(self)
            action.setShortcut(QKeySequence(f"Ctrl+{i+1}"))
            action.triggered.connect(lambda checked, k=key: self._show_page(k))
            self.addAction(action)
        esc = QAction(self)
        esc.setShortcut(QKeySequence("Escape"))
        esc.triggered.connect(self._auto.stop_all)
        self.addAction(esc)

        # Tooltips
        self._mode_sel.setToolTip("输入模式：内核驱动(推荐)使用Interception驱动需要管理员权限；Arduino使用串口硬件模拟键鼠")
        self._win_combo.setToolTip("选择要自动化的游戏窗口，程序会向该窗口发送按键和鼠标操作")
        rf.setToolTip("刷新窗口列表")
        self._rmin.setToolTip("每次操作前随机等待的最小毫秒数，模拟人类操作节奏")
        self._rmax.setToolTip("每次操作前随机等待的最大毫秒数")

    def _make_page(self, key):
        m = {"battle":BattlePage,"skip":SkipPage,"mine":MinePage,"release":ReleasePage,"throw":ThrowPage,"boxcheck":BoxCheckPage,"visitor":VisitorPage,"serial":SerialManagerWidget}
        cls = m[key]; return cls() if key=="serial" else cls(self._auto)

    def _show_page(self, key):
        for b,k in self._nav: b.setChecked(k==key)
        self._stack.setCurrentWidget(self._pg[key])
        self._plbl.setText(dict(self.PAGES).get(key,key))
        self._update_nav_styles()
        # Notify all pages of visibility change
        for k, pg in self._pg.items():
            if hasattr(pg, 'set_active'):
                pg.set_active(k == key)

    def _refresh_window_list(self):
        from roco_auto.core.window_finder import list_all_visible_windows
        ws = list_all_visible_windows()
        self._win_combo.blockSignals(True); self._win_combo.clear()
        self._win_combo.addItem("(未选择)", None)
        # Try to restore saved window
        saved_title = self._config.load().get("window_title", "")
        matched_idx = -1
        for i, w in enumerate(ws):
            label = f"{w['title'][:35]}  ({w['width']}x{w['height']})"
            self._win_combo.addItem(label, (w["hwnd"], w["title"]))
            if w["title"] == saved_title and matched_idx < 0:
                matched_idx = i + 1  # +1 for "(未选择)"

        self._win_combo.blockSignals(False)

        # First-run: if no saved title, try to auto-match common game windows
        if matched_idx < 0 and not saved_title:
            for i, w in enumerate(ws):
                for keyword in GAME_WINDOW_KEYWORDS:
                    if keyword.lower() in w["title"].lower():
                        matched_idx = i + 1  # +1 for "(未选择)"
                        break
                if matched_idx >= 0:
                    break

        if matched_idx >= 0:
            self._win_combo.setCurrentIndex(matched_idx)
            # First-run guidance: highlight window selector
            if not saved_title:
                self._slbl.setText("已自动检测游戏窗口，请确认后开始使用")
                self._slbl.setStyleSheet("color:#4ade80; font-size:12px; font-weight:bold;")

    def _on_window_selected(self, _i):
        data = self._win_combo.currentData()
        if data is None:
            self._auto.set_target_window(None, "")
            return
        hwnd, title = data
        self._auto.set_target_window(hwnd, title)
        # Save selection for next restart
        self._config.update({"window_title": title})
        self._config.save()

    def _on_mode_changed(self, i):
        if i==0:
            self._auto.set_interception_mode()
            ok = self._auto.is_backend_ready()
            self._clbl.setText("● 驱动就绪" if ok else "○ 驱动未加载")
            self._clbl.setStyleSheet(f"color:{'#4ade80' if ok else '#ff5c5c'}; font-size:11px;")
        else:
            from roco_auto.core.input_backend import NoopBackend
            self._auto._backend = NoopBackend()
            self._clbl.setText("○ 等待 Arduino"); self._clbl.setStyleSheet("color:#ce9178; font-size:11px;")

    def _wire_serial(self):
        sp = self._pg.get("serial")
        if not isinstance(sp, SerialManagerWidget): return
        self._serial_timer = QTimer(self, interval=2000)
        def ck():
            if self._mode_sel.currentIndex() == 1:  # Arduino mode
                if sp.is_connected:
                    self._clbl.setText("● Arduino 已连接"); self._clbl.setStyleSheet("color:#4ade80; font-size:11px;")
                    self._slbl.setText("Arduino 已就绪"); self._auto.set_arduino_client(sp.client)
                else:
                    self._clbl.setText("○ 等待 Arduino"); self._clbl.setStyleSheet("color:#ce9178; font-size:11px;")
            # In kernel driver mode, status is set by _on_mode_changed — no need to poll
        self._serial_timer.timeout.connect(ck)
        self._serial_timer.start()

    def _toggle_theme(self):
        self._is_dark = not self._is_dark
        self._theme_btn.setText("  ☀  亮色主题" if self._is_dark else "  🌙  暗色主题")
        self._apply_theme()
        from roco_auto.ui.hotkey_capture import HotkeyCapture
        HotkeyCapture.set_theme_dark(self._is_dark)

    def _apply_theme(self):
        self.setStyleSheet(_DARK_QSS if self._is_dark else _LIGHT_QSS)

        # Bar backgrounds
        sbbg = "#252540" if self._is_dark else "#e8e8f0"
        topbg = "#1a1a30" if self._is_dark else "#ffffff"
        barbg = "#1a1a30" if self._is_dark else "#fafafa"
        border = "#333" if self._is_dark else "#e0e0e0"

        self._sidebar.setStyleSheet(f"background:{sbbg};")
        self._topbar.setStyleSheet(f"background:{topbg}; border-bottom:1px solid {border};")
        self._statusbar.setStyleSheet(f"background:{barbg}; border-top:1px solid {border};")

        self._update_nav_styles()

        # Theme button
        tbbg = "#353560" if self._is_dark else "#d8e0f0"
        tbc = "#b0b0d0" if self._is_dark else "#555"
        nht = "#ffffff" if self._is_dark else "#1a1a1a"
        self._theme_btn.setStyleSheet(
            f"QPushButton{{background:{tbbg};color:{tbc};border:none;border-radius:6px;"
            f"margin:4px 8px;font-size:11px;}}QPushButton:hover{{color:{nht}}}")

        self._slbl.setStyleSheet("color:#6a9955; font-size:11px;")
        self._plbl.setStyleSheet(f"color:{'#888' if self._is_dark else '#777'}; font-size:12px;")

    def _update_nav_styles(self):
        """Refresh sidebar nav button styles after page switch or theme change."""
        nc = "#b0b0d0" if self._is_dark else "#555"
        nh = "#353560" if self._is_dark else "#d8e0f0"
        nht = "#ffffff" if self._is_dark else "#1a1a1a"
        nab = "#6c8cff33" if self._is_dark else "#5b6ce033"
        nat = "#6c8cff" if self._is_dark else "#5b6ce0"
        for btn, key in self._nav:
            active = self._stack.currentWidget() == self._pg.get(key)
            if active:
                btn.setStyleSheet(
                    f"QPushButton{{background:{nab};color:{nat};border:none;"
                    f"border-left:3px solid {nat};text-align:left;font-size:13px;"
                    f"font-weight:bold;padding-left:9px;}}"
                    f"QPushButton:hover{{background:{nh};color:{nht}}}")
            else:
                btn.setStyleSheet(
                    f"QPushButton{{background:transparent;color:{nc};border:none;"
                    f"text-align:left;font-size:13px;padding-left:12px;}}"
                    f"QPushButton:hover{{background:{nh};color:{nht}}}")
