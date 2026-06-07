# -*- coding: utf-8 -*-
"""Polished card-based mode pages with tooltips and visibility-aware timers."""

import time

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QPushButton, QLabel, QSpinBox, QComboBox,
    QCheckBox, QSlider, QLineEdit,
)
from PySide6.QtCore import Qt, QTimer, Signal

from roco_auto.core.game_automation import GameAutomation


def _fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def _toggle_btn(start_label: str, start_fn, auto: GameAutomation, status_name: str = "", stop_fn=None) -> QPushButton:
    btn = QPushButton(start_label)
    btn.setObjectName("__toggle__")
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(
        "QPushButton#__toggle__ { font-size:14px; font-weight:bold; padding:10px 28px;"
        " border:none; border-radius:8px; background:#6c8cff; color:#fff; }"
        "QPushButton#__toggle__:hover { background:#5a7aee; }")

    def _upd():
        if auto.is_running():
            btn.setText("■ 停止")
            btn.setStyleSheet(
                "QPushButton#__toggle__ { font-size:14px; font-weight:bold; padding:10px 28px;"
                " border:none; border-radius:8px; background:#ff5c5c; color:#fff; }")
        else:
            btn.setText(start_label)
            btn.setStyleSheet(
                "QPushButton#__toggle__ { font-size:14px; font-weight:bold; padding:10px 28px;"
                " border:none; border-radius:8px; background:#6c8cff; color:#fff; }"
                "QPushButton#__toggle__:hover { background:#5a7aee; }")

    def _update_status(is_start):
        if not status_name: return
        try:
            from PySide6.QtWidgets import QApplication
            from roco_auto.ui.main_window import MainWindow
            for w in QApplication.topLevelWidgets():
                if isinstance(w, MainWindow):
                    w._slbl.setText(f"{status_name} {'已启动' if is_start else '已停止'}")
                    break
        except: pass

    def _toggle():
        if not auto.is_running():
            start_fn()
            _update_status(True)
        else:
            if stop_fn: stop_fn()
            else: auto.stop_all()
            _update_status(False)

    t = QTimer(btn); t.timeout.connect(_upd); t.start(300)
    btn._timer = t
    btn.clicked.connect(_toggle)
    return btn


# ═══════════════════════════════════════════════  BATTLE  ═══

class BattlePage(QWidget):
    def __init__(self, auto, parent=None):
        super().__init__(parent); self._a = auto; self._init_ui()

    def set_active(self, active: bool):
        for t in self._timers:
            if active: t.start()
            else: t.stop()

    def _upd(self):
        e = time.time() - self._a.battle_start_time if self._a.is_running() and self._a.battle_start_time > 0 else 0
        self._sl.setText(f"{self._a.battle_count} 次  |  {_fmt_time(e)}")

    def _init_ui(self):
        l = QVBoxLayout(self); l.setContentsMargins(20, 16, 20, 16); l.setSpacing(10)
        self._timers = []

        l.addWidget(_title("⚔ 自动战斗"))
        l.addWidget(_desc("反复按下指定战斗按键,间隔可配置。适用于挂机刷野怪、自动练级等场景。"))

        l.addLayout(_hotkey("hotkey_battle", self._a))

        g = QGroupBox("战斗设置"); gl = QGridLayout(g); gl.setSpacing(8)
        gl.addWidget(QLabel("战斗按键:"), 0, 0)
        kb = QComboBox(); kb.addItems(["1","2","3","4","X"]); kb.setCurrentText(self._a.battle_key)
        kb.setToolTip("选择要在战斗中反复按下的按键")
        kb.currentTextChanged.connect(lambda v: setattr(self._a, "battle_key", v)); gl.addWidget(kb, 0, 1)

        gl.addWidget(QLabel("战斗间隔(ms):"), 1, 0)
        s = QSpinBox(); s.setRange(500,30000); s.setValue(self._a.battle_interval); s.setSingleStep(500)
        s.setToolTip("两次出招之间的间隔毫秒数")
        s.valueChanged.connect(lambda v: setattr(self._a, "battle_interval", v)); gl.addWidget(s, 1, 1)

        gl.addWidget(QLabel("启动延迟(ms):"), 2, 0)
        s2 = QSpinBox(); s2.setRange(1000,30000); s2.setValue(self._a.first_start_delay); s2.setSingleStep(1000)
        s2.setToolTip("点击开始后等待多少毫秒才发出第一招")
        s2.valueChanged.connect(lambda v: setattr(self._a, "first_start_delay", v)); gl.addWidget(s2, 2, 1)
        l.addWidget(g)

        btns = QHBoxLayout()
        self._tbtn = _toggle_btn("开始自动战斗", self._a.start_auto_battle, self._a, "自动战斗")
        btns.addWidget(self._tbtn); btns.addStretch()
        self._sl = _stat(); btns.addWidget(self._sl)
        t = QTimer(self, timeout=self._upd, interval=500); t.start(); self._timers.append(t)
        l.addLayout(btns); l.addStretch()


# ═══════════════════════════════════════  Skip floating window  ═══

class _SkipFloatingWindow(QWidget):
    stop_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("跳过剧情运行中")
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setMinimumWidth(180)
        self.setStyleSheet("background:#1a1a2e; border-radius:8px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 6); layout.setSpacing(4)

        title = QLabel("跳过剧情"); title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color:#6c8cff; font-size:13px; font-weight:bold; border:none; background:transparent;")
        layout.addWidget(title)

        self._status_lbl = QLabel("等待检测..."); self._status_lbl.setAlignment(Qt.AlignCenter)
        self._status_lbl.setStyleSheet("color:#aaa; font-size:12px; padding:6px 0; border:none; background:transparent;")
        layout.addWidget(self._status_lbl)

        bar = QWidget(); bar.setStyleSheet("background:transparent;")
        bl = QHBoxLayout(bar); bl.setContentsMargins(0, 4, 0, 0); bl.setSpacing(4)
        bl.addStretch()
        stop_btn = QPushButton("停止"); stop_btn.setCursor(Qt.PointingHandCursor); stop_btn.setFixedSize(44, 22)
        stop_btn.setStyleSheet("QPushButton{font-size:11px;font-weight:bold;border:none;border-radius:3px;background:#ff5c5c;color:#fff;}QPushButton:hover{background:#ee4444;}")
        stop_btn.clicked.connect(self.stop_requested.emit)
        bl.addWidget(stop_btn)
        layout.addWidget(bar)

        self._drag_pos = None

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


# ═══════════════════════════════════════════════════  SKIP  ═══

class SkipPage(QWidget):
    def __init__(self, auto, parent=None):
        super().__init__(parent); self._a = auto
        self._main_window = None; self._floating = None
        self._skip_status = "等待检测..."
        self._orig_skip_start = self._a.start_skip_story  # save before override
        self._a.start_skip_story = self._start_skip  # override so hotkey gets callbacks
        self._init_ui()

    def set_active(self, active: bool):
        for t in self._timers:
            if active: t.start()
            else: t.stop()

    def _get_main_window(self):
        if self._main_window is None: self._main_window = self.window()
        return self._main_window

    def _start_skip(self):
        def on_status(text): self._skip_status = text
        def on_detect(dets):
            names = ", ".join(f"{d['class']}@{d['confidence']:.1f}" for d in dets[:2])
            self._skip_status = f"检测到: {names}"
        self._orig_skip_start(on_status=on_status, on_detect=on_detect)

    def _stop_skip(self):
        if self._a.is_running():
            self._a.stop_all()
        if self._floating:
            self._floating.close(); self._floating = None
        mw = self._get_main_window()
        if mw: mw.showNormal()

    def _init_ui(self):
        l = QVBoxLayout(self); l.setContentsMargins(20,16,20,16); l.setSpacing(10)
        self._timers = []


        l.addWidget(_title("⏭ 跳过剧情 (YOLO)"))
        l.addWidget(_desc("自动检测游戏画面中的剧情提示，并执行对应操作来跳过对话和过场动画，省去反复手动按键的麻烦。"))

        l.addLayout(_hotkey("hotkey_skip", self._a))

        g = QGroupBox("YOLO 模型设置"); gl = QGridLayout(g); gl.setSpacing(8)
        gl.addWidget(QLabel("置信度阈值:"), 0, 0)
        c = QSpinBox(); c.setRange(10,100); c.setValue(int(self._a.skip_confidence*100))
        c.setSuffix("%"); c.setToolTip("只有置信度高于此值的检测结果才被采纳，值越高越不容易误判")
        c.valueChanged.connect(lambda v: setattr(self._a, "skip_confidence", v/100.0)); gl.addWidget(c, 0, 1)

        gl.addWidget(QLabel("检测间隔(ms):"), 1, 0)
        p = QSpinBox(); p.setRange(100,3000); p.setValue(self._a.skip_poll_interval); p.setSingleStep(50)
        p.setToolTip("两次屏幕检测之间的间隔，越小越灵敏但越吃CPU")
        p.valueChanged.connect(lambda v: setattr(self._a, "skip_poll_interval", v)); gl.addWidget(p, 1, 1)

        l.addWidget(g)

        btns = QHBoxLayout()
        self._tbtn = _toggle_btn("开始跳过剧情", self._start_skip, self._a, "跳过剧情", self._stop_skip)
        btns.addWidget(self._tbtn); btns.addStretch()
        self._skip_status = "等待检测..."
        self._sl = _stat(); btns.addWidget(self._sl)
        t = QTimer(self, timeout=self._upd, interval=500); t.start(); self._timers.append(t)
        self._fw_timer = QTimer(self, timeout=self._check_float, interval=300)
        self._fw_timer.start(); self._timers.append(self._fw_timer)
        l.addLayout(btns); l.addStretch()

    def _check_float(self):
        """Auto-show floating window when skip runner starts."""
        if self._a.is_running() and self._floating is None:
            try:
                self._floating = _SkipFloatingWindow()
                self._floating.stop_requested.connect(self._stop_skip)
                mw = self._get_main_window()
                if mw and hasattr(mw, 'global_stopped'):
                    mw.global_stopped.connect(self._stop_skip)
                screen = self.screen().availableGeometry()
                self._floating.adjustSize()
                self._floating.move(screen.right() - self._floating.width() - 20, screen.top() + 60)
                self._floating.show()
                if mw: mw.showMinimized()
            except Exception:
                pass

    def _upd(self):
        e = time.time() - self._a.skip_start_time if self._a.is_running() and self._a.skip_start_time > 0 else 0
        s = getattr(self, '_skip_status', '等待检测...')
        self._sl.setText(f"{self._a.skip_count} 次  |  {_fmt_time(e)}  |  {s}")
        if self._floating:
            self._floating._status_lbl.setText(s[:30])

    def _test(self):
        y = self._a._get_yolo()
        if y is not None:
            names = list(y.names.values()) if hasattr(y, 'names') else []
            self._ms.setText(f"已加载 ({len(names)} 类: {', '.join(names)})")
            self._ms.setStyleSheet("color:#4ade80;")
        else:
            self._ms.setText("加载失败"); self._ms.setStyleSheet("color:#ff5c5c;")


# ═══════════════════════════════════════════════════  MINE  ═══

class MinePage(QWidget):
    def __init__(self, auto, parent=None):
        super().__init__(parent); self._a = auto; self._init_ui()

    def set_active(self, active: bool):
        for t in self._timers:
            if active: t.start()
            else: t.stop()

    def _init_ui(self):
        l = QVBoxLayout(self); l.setContentsMargins(20,16,20,16); l.setSpacing(10)
        self._timers = []

        l.addWidget(_title("⛏ 采矿切宠"))
        l.addWidget(_desc("监听鼠标左键:采矿松手后自动按 2→3→4→5→6 循环切换精灵。只需点矿,切宠全自动。"))

        l.addLayout(_hotkey("hotkey_mine", self._a))

        g = QGroupBox("切宠设置"); gl = QGridLayout(g); gl.setSpacing(8)
        gl.addWidget(QLabel("切换按键:"), 0, 0)
        kl = QLabel("2 → 3 → 4 → 5 → 6 (循环)"); kl.setStyleSheet("font-weight:bold;"); gl.addWidget(kl, 0, 1)

        gl.addWidget(QLabel("切换延迟(ms):"), 1, 0)
        pd = QSpinBox(); pd.setRange(0,2000); pd.setValue(self._a.mine_switch_delay)
        pd.setToolTip("松开鼠标后等待多少毫秒再切换精灵")
        pd.valueChanged.connect(lambda v: setattr(self._a, "mine_switch_delay", v)); gl.addWidget(pd, 1, 1)
        l.addWidget(g)

        btns = QHBoxLayout()
        self._tbtn = _toggle_btn("开始采矿切宠", self._a.start_mine_listen, self._a, "采矿切宠")
        btns.addWidget(self._tbtn); btns.addStretch()
        # Toggle timer runs always (not in _timers)
        l.addLayout(btns); l.addStretch()


# ═════════════════════════════════════════════════  RELEASE  ═══

class ReleasePage(QWidget):
    def __init__(self, auto, parent=None):
        super().__init__(parent); self._a = auto
        self._rt = QTimer(self, timeout=self._upd, interval=500)
        self._timers = [self._rt]
        self._init_ui(); self._start_hk()
        self._rt.start()

    def set_active(self, active: bool):
        for t in self._timers:
            if active: t.start()
            else: t.stop()

    def _init_ui(self):
        l = QVBoxLayout(self); l.setContentsMargins(20,16,20,16); l.setSpacing(10)

        l.addWidget(_title("♻ 一键放生"))
        l.addWidget(_desc("自动计算 6×5=30 个宠物位置放生。F8/F9 捕获对角,F10 确认,F11 翻页。坐标存比例,换分辨率自适应。"))

        l.addLayout(_hotkey("hotkey_release", self._a))

        cap = QGroupBox("坐标捕获  F8-F11热键 / 或点击手动捕获按钮")
        cl = QGridLayout(cap); cl.setSpacing(6)
        self._tl_lbl = _cap_row(cl, "第一只宠物(左上):", 0, "F9", self._capture_release_abs, "release_x0", "release_y0")
        self._br_lbl = _cap_row(cl, "最后一只宠物(右下):", 1, "F10", self._capture_release_abs, "release_x30", "release_y30")
        self._cf_lbl = _cap_row(cl, "确认按钮:", 2, "F11", self._capture_coord, "release_confirm_rel", None)
        self._nx_lbl = _cap_row(cl, "翻页:", 3, "F12", self._capture_coord, "release_next_page_rel", None)

        cl.addWidget(QLabel("随机偏移:"), 4, 0)
        self._js = QSpinBox(); self._js.setRange(0,20); self._js.setValue(self._a.release_click_jitter)
        self._js.setSuffix(" px"); self._js.setToolTip("点击位置随机偏移像素数，防止每次点击同一坐标被检测")
        self._js.valueChanged.connect(lambda v: setattr(self._a, "release_click_jitter", v))
        cl.addWidget(self._js, 4, 1)
        l.addWidget(cap)

        g2 = QGroupBox("放生设置"); gl = QGridLayout(g2); gl.setSpacing(8)
        gl.addWidget(QLabel("每步延迟(ms):"), 0, 0)
        pd = QSpinBox(); pd.setRange(1,1000); pd.setValue(self._a.release_per_step)
        pd.setToolTip("点击每个宠物之间的延迟毫秒数，太快可能导致游戏漏点击")
        pd.valueChanged.connect(lambda v: setattr(self._a, "release_per_step", v)); gl.addWidget(pd, 0, 1)

        self._ap = QCheckBox("放生所有页面(翻页)"); self._ap.setChecked(self._a.release_all_pages)
        self._ap.setToolTip("自动翻页放生所有宠物，而不是只放生当前页面")
        self._ap.toggled.connect(lambda v: setattr(self._a, "release_all_pages", v))
        gl.addWidget(self._ap, 1, 0, 1, 2)
        l.addWidget(g2)

        btns = QHBoxLayout()
        self._tbtn = _toggle_btn("开始一键放生", self._a.start_release_pets, self._a, "一键放生")
        btns.addWidget(self._tbtn); btns.addStretch()
        # Toggle timer runs always (not in _timers)
        l.addLayout(btns); l.addStretch()

    def _upd(self):
        w = self._a.get_target_window()
        # Show grid coords
        x0, y0 = self._a.release_x0, self._a.release_y0
        x30, y30 = self._a.release_x30, self._a.release_y30
        if x0 and y0:
            self._tl_lbl.setText(f"({x0}, {y0})")
            self._tl_lbl.setStyleSheet("color:#4ade80;")
        else:
            self._tl_lbl.setText("未捕获")
            self._tl_lbl.setStyleSheet("color:#ff5c5c;")
        if x30 and y30:
            self._br_lbl.setText(f"({x30}, {y30})")
            self._br_lbl.setStyleSheet("color:#4ade80;")
            # Show computed spacing
            dx = (x30 - x0) // 5 if x0 and x30 else 0
            dy = (y30 - y0) // 4 if y0 and y30 else 0
            self._br_lbl.setText(f"({x30}, {y30})  dx={dx}, dy={dy}")
        else:
            self._br_lbl.setText("未捕获")
            self._br_lbl.setStyleSheet("color:#ff5c5c;")
        # Confirm + next page
        if not w:
            self._cf_lbl.setText("未捕获"); self._nx_lbl.setText("未捕获")
            return
        for lbl, attr in [(self._cf_lbl, "release_confirm_rel"), (self._nx_lbl, "release_next_page_rel")]:
            val = getattr(self._a, attr)
            lbl.setText(f"相对({val[0]:.3f}, {val[1]:.3f})")
            lbl.setStyleSheet("font-weight:bold;")

    def _capture_coord(self, attr):
        """Capture current mouse position and save as relative coordinate."""
        import ctypes
        from ctypes import wintypes
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        w = self._a.get_target_window()
        if not w: return
        rx = (pt.x - w["left"]) / w["width"]
        ry = (pt.y - w["top"]) / w["height"]
        setattr(self._a, attr, (rx, ry))

    def _capture_release_abs(self, x_attr, y_attr):
        """Capture current mouse position as absolute screen coordinates."""
        import ctypes
        from ctypes import wintypes
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        setattr(self._a, x_attr, pt.x)
        setattr(self._a, y_attr, pt.y)

    def _start_hk(self):
        try:
            from roco_auto.core.hotkey_manager import GlobalHotkeyManager
            import ctypes; from ctypes import wintypes
            mgr = GlobalHotkeyManager()
            def get_pos():
                pt = wintypes.POINT(); ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                return pt.x, pt.y
            def cap_abs(xa, ya):
                x, y = get_pos()
                setattr(self._a, xa, x); setattr(self._a, ya, y)
            def cap_rel(attr):
                x, y = get_pos()
                w = self._a.get_target_window()
                if not w: return
                rx = (x - w["left"]) / w["width"]
                ry = (y - w["top"]) / w["height"]
                setattr(self._a, attr, (rx, ry))
            mgr.register("rel_f9", "F9", lambda: cap_abs("release_x0", "release_y0"))
            mgr.register("rel_f10", "F10", lambda: cap_abs("release_x30", "release_y30"))
            mgr.register("rel_f11", "F11", lambda: cap_rel("release_confirm_rel"))
            mgr.register("rel_f12", "F12", lambda: cap_rel("release_next_page_rel"))
        except Exception:
            import logging
            logging.getLogger(__name__).warning("ReleasePage hotkey registration failed", exc_info=True)


def _cap_row(layout, label, row, hotkey, handler, attr, attr2=None):
    layout.addWidget(QLabel(f"{label} ({hotkey})"), row, 0)
    lbl = QLabel("未捕获"); lbl.setStyleSheet("color:#ff5c5c;")
    layout.addWidget(lbl, row, 1)
    return lbl


# ═══════════════════════════════════════════════════  THROW  ═══

class ThrowPage(QWidget):
    def __init__(self, auto, parent=None):
        super().__init__(parent); self._a = auto; self._init_ui()

    def set_active(self, active: bool):
        for t in self._timers:
            if active: t.start()
            else: t.stop()

    def _upd(self):
        c = self._a.throw_count
        e = time.time() - self._a.throw_start_time if self._a.is_running() and self._a.throw_start_time > 0 else 0
        r = c / (e/60) if e > 0 else 0
        self._sl.setText(f"{c} 次  |  {_fmt_time(e)}  |  {r:.0f} 次/分")

    def _init_ui(self):
        l = QVBoxLayout(self); l.setContentsMargins(20,16,20,16); l.setSpacing(10)
        self._timers = []

        l.addWidget(_title("⚾ 自动丢球"))
        l.addWidget(_desc("模拟按住鼠标再松开的循环操作。先手动选球类型,移动鼠标到目标,再启动。"))

        l.addLayout(_hotkey("hotkey_throw", self._a))

        g = QGroupBox("丢球设置"); gl = QGridLayout(g); gl.setSpacing(8)

        gl.addWidget(QLabel("按住时长(ms):"), 0, 0)
        ht = QSpinBox(); ht.setRange(50,5000); ht.setValue(self._a.throw_hold_time); ht.setSingleStep(50)
        ht.setToolTip("鼠标按住多久再松开，模拟按住力度")
        ht.valueChanged.connect(lambda v: setattr(self._a, "throw_hold_time", v)); gl.addWidget(ht, 0, 1)

        gl.addWidget(QLabel("丢球速度:"), 1, 0)
        sr = QHBoxLayout()
        sr.addWidget(QLabel("快"))
        td = QSlider(Qt.Horizontal); td.setRange(200,5000); td.setValue(self._a.throw_base_delay)
        td.setToolTip("每次丢球之间的间隔，越靠近快频率越高")
        self._spd = QLabel(f"{self._a.throw_base_delay} ms"); self._spd.setStyleSheet("font-weight:bold; min-width:50px;")
        td.valueChanged.connect(lambda v: (setattr(self._a,"throw_base_delay",v), self._spd.setText(f"{v} ms")))
        sr.addWidget(td); sr.addWidget(QLabel("慢")); sr.addWidget(self._spd)
        gl.addLayout(sr, 1, 1)
        l.addWidget(g)

        lg = QGroupBox("次数限制"); ll = QGridLayout(lg); ll.setSpacing(8)
        self._lc = QCheckBox("启用次数限制"); self._lc.setChecked(self._a.throw_limit_enabled)
        self._lc.setToolTip("达到指定次数后自动停止或等待")
        self._lc.toggled.connect(lambda v: setattr(self._a, "throw_limit_enabled", v)); ll.addWidget(self._lc, 0, 0, 1, 2)

        ll.addWidget(QLabel("丢球次数:"), 1, 0)
        lc2 = QSpinBox(); lc2.setRange(1,99999); lc2.setValue(self._a.throw_limit_count)
        lc2.setToolTip("达到此次数后执行限制动作")
        lc2.valueChanged.connect(lambda v: setattr(self._a, "throw_limit_count", v)); ll.addWidget(lc2, 1, 1)

        ll.addWidget(QLabel("达到后:"), 2, 0)
        la = QComboBox(); la.addItems(["stop (停止)","wait (等待)"])
        la.setCurrentIndex(0 if self._a.throw_limit_action=="stop" else 1)
        la.setToolTip("stop=停止丢球, wait=等待一段时间后继续")
        la.currentIndexChanged.connect(lambda i: setattr(self._a,"throw_limit_action","stop" if i==0 else "wait")); ll.addWidget(la, 2, 1)

        ll.addWidget(QLabel("等待时长(ms):"), 3, 0)
        lw = QSpinBox(); lw.setRange(1000,300000); lw.setValue(self._a.throw_limit_wait_ms); lw.setSingleStep(1000)
        lw.setToolTip("wait模式下等待多少毫秒后恢复丢球")
        lw.valueChanged.connect(lambda v: setattr(self._a, "throw_limit_wait_ms", v)); ll.addWidget(lw, 3, 1)
        l.addWidget(lg)

        self._sl = _stat(); l.addWidget(self._sl)

        btns = QHBoxLayout()
        self._tbtn = _toggle_btn("开始自动丢球", self._a.start_auto_throw, self._a, "自动丢球")
        btns.addWidget(self._tbtn); btns.addStretch()
        # Toggle timer runs always (not in _timers)
        l.addLayout(btns)
        t = QTimer(self, timeout=self._upd, interval=500); t.start(); self._timers.append(t)
        l.addStretch()


# ── Helpers ─────────────────────────────────────────────

def _title(t): return _lbl(t, "font-size:20px; font-weight:bold; padding-bottom:2px;")
def _desc(t): return _lbl(t, "padding:2px 0 8px 0; line-height:1.5;", True)
def _stat(): return _lbl("0 次 | 00:00 | 0 次/分", "font-weight:bold; font-size:12px;")

def _lbl(text, style, wrap=False):
    l = QLabel(text); l.setStyleSheet(style)
    if wrap: l.setWordWrap(True)
    return l

def _on_hk_change(auto, attr, new_key):
    """Called when user changes a hotkey — re-register with global hotkey manager."""
    setattr(auto, attr, new_key)
    try:
        from roco_auto.ui.main_window import MainWindow
        # Trigger re-registration via the main window
        mw = None
        from PySide6.QtWidgets import QApplication
        for w in QApplication.topLevelWidgets():
            if isinstance(w, MainWindow):
                mw = w; break
        if mw and hasattr(mw, '_register_hotkeys'):
            mw._register_hotkeys()
    except Exception:
        pass


def _hotkey(attr, auto):
    row = QHBoxLayout()
    from roco_auto.ui.hotkey_capture import HotkeyCapture
    hk = HotkeyCapture(getattr(auto, attr, ""))
    hk.setToolTip("点击后按下组合键(如CTRL+Z)来设置启停热键，按一次启动再按停止")
    hk.key_changed.connect(lambda k, a=auto, at=attr: _on_hk_change(a, at, k))
    row.addWidget(QLabel("启停热键:")); row.addWidget(hk)
    row.addWidget(QLabel("按一次启动,再按停止")); row.addStretch()
    return row
