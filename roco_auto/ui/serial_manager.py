"""Serial port manager tab — connect/disconnect/test Arduino."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QComboBox, QPushButton, QLabel, QTextEdit, QSpinBox,
)
from PySide6.QtCore import Qt, QTimer

from roco_auto.core.port_discovery import discover_arduino_ports, list_all_ports
from roco_auto.core.serial_client import SerialClient


class SerialManagerWidget(QWidget):
    """Tab for managing the Arduino serial connection."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client: SerialClient | None = None
        self._connected = False
        self._setup_ui()
        self._scan_ports()

        # Auto-rescan every 2 seconds
        self._scan_timer = QTimer(self)
        self._scan_timer.timeout.connect(self._scan_ports)
        self._scan_timer.start(2000)
        self._timers = [self._scan_timer]

    def set_active(self, active: bool):
        for t in self._timers:
            if active:
                t.start()
            else:
                t.stop()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Title + description
        title = QLabel("串口管理")
        title.setStyleSheet("font-size:20px; font-weight:bold; padding-bottom:2px;")
        layout.addWidget(title)
        desc = QLabel("连接 Arduino Leonardo/Micro 设备。Arduino 作为 USB HID 硬件模拟键盘鼠标，\n"
                      "相比纯软件方案更难被游戏反作弊系统检测。连接成功后，其他页面的自动化功能才能正常工作。\n"
                      "波特率固定为 115200，与 roco_firmware 固件保持一致。")
        desc.setStyleSheet("padding:2px 0 8px 0; line-height:1.5;")
        layout.addWidget(desc)

        # Port selection
        port_group = QGroupBox("串口设置")
        port_layout = QHBoxLayout(port_group)

        port_layout.addWidget(QLabel("端口:"))
        self._port_combo = QComboBox()
        self._port_combo.setMinimumWidth(150)
        port_layout.addWidget(self._port_combo)

        port_layout.addWidget(QLabel("波特率:"))
        self._baud_spin = QSpinBox()
        self._baud_spin.setRange(9600, 115200)
        self._baud_spin.setValue(115200)
        self._baud_spin.setEnabled(False)
        port_layout.addWidget(self._baud_spin)

        self._scan_btn = QPushButton("刷新")
        self._scan_btn.clicked.connect(self._scan_ports)
        port_layout.addWidget(self._scan_btn)

        self._connect_btn = QPushButton("连接")
        self._connect_btn.clicked.connect(self._toggle_connection)
        port_layout.addWidget(self._connect_btn)

        port_layout.addStretch()
        layout.addWidget(port_group)

        # Test commands
        test_group = QGroupBox("测试指令")
        test_layout = QHBoxLayout(test_group)
        self._test_btn = QPushButton("发送 TAB")
        self._test_btn.clicked.connect(lambda: self._send_command("TAB"))
        self._test_btn.setEnabled(False)
        test_layout.addWidget(self._test_btn)

        stop_btn = QPushButton("紧急停止 STOP")
        stop_btn.setStyleSheet("color: red; font-weight: bold;")
        stop_btn.clicked.connect(lambda: self._send_command("STOP"))
        stop_btn.setEnabled(False)
        self._stop_btn = stop_btn

        test_layout.addWidget(self._stop_btn)
        test_layout.addStretch()
        layout.addWidget(test_group)

        # Log output
        log_group = QGroupBox("通信日志")
        log_layout = QVBoxLayout(log_group)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.document().setMaximumBlockCount(500)
        log_layout.addWidget(self._log)

        clear_btn = QPushButton("清空日志")
        clear_btn.clicked.connect(self._log.clear)
        log_layout.addWidget(clear_btn)
        layout.addWidget(log_group)

    def _scan_ports(self):
        """Refresh the port list, preserving current selection."""
        current = self._port_combo.currentText()
        self._port_combo.clear()
        arduino_ports = discover_arduino_ports()
        if arduino_ports:
            for info in arduino_ports:
                self._port_combo.addItem(f"{info.port} — {info.description}", info.port)
        else:
            all_ports = list_all_ports()
            for info in all_ports:
                self._port_combo.addItem(f"{info.port} — {info.description}", info.port)
        if not self._port_combo.count():
            self._port_combo.addItem("(未检测到串口)")

        # Restore previous selection
        for i in range(self._port_combo.count()):
            if self._port_combo.itemData(i) == current:
                self._port_combo.setCurrentIndex(i)
                return

    def _toggle_connection(self):
        if self._connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        port_data = self._port_combo.currentData()
        if not port_data:
            self._log_msg("错误: 没有可用的串口")
            return

        self._client = SerialClient()
        self._client.connected.connect(self._on_connected)
        self._client.disconnected.connect(self._on_disconnected)
        self._client.response_received.connect(self._on_response)
        self._client.error_occurred.connect(self._on_error)
        self._client.open(port_data)

    def _disconnect(self):
        if self._client:
            self._client.close()
            self._client = None
        self._connected = False
        self._connect_btn.setText("连接")
        self._test_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._log_msg("已断开连接")

    def _on_connected(self, port_name):
        self._connected = True
        self._connect_btn.setText("断开")
        self._test_btn.setEnabled(True)
        self._stop_btn.setEnabled(True)
        self._log_msg(f"已连接: {port_name}")

    def _on_disconnected(self):
        self._connected = False
        self._connect_btn.setText("连接")
        self._test_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._log_msg("连接已断开")

    def _on_response(self, resp_type, payload):
        if resp_type == "cmd":
            self._log_msg(f"<- CMD: {payload}")
        elif resp_type == "bad":
            self._log_msg(f"<- BAD: {payload}")
        elif resp_type == "ok":
            self._log_msg(f"<- OK {payload}")
        elif resp_type == "pos":
            self._log_msg(f"<- POS: {payload}")
        else:
            self._log_msg(f"<- {payload}")

    def _on_error(self, message):
        self._log_msg(f"错误: {message}")

    def _send_command(self, cmd: str):
        if self._client and self._connected:
            self._client.send(cmd)
            self._log_msg(f"-> {{{cmd}}}")

    def _log_msg(self, text: str):
        self._log.append(text)

    @property
    def client(self) -> SerialClient | None:
        return self._client

    @property
    def is_connected(self) -> bool:
        return self._connected
