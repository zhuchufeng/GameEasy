"""Async serial client using QThread for non-blocking communication."""

from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker
from collections import deque
import serial
import logging

from .serial_protocol import encode_command, decode_response

logger = logging.getLogger(__name__)


class SerialClient(QThread):
    """QThread-based serial I/O worker for Arduino communication.

    Signals:
      connected(port_name)     — connection established
      disconnected()           — connection lost
      response_received(type, payload) — response parsed from Arduino
      error_occurred(message)  — error notification
    """

    connected = Signal(str)
    disconnected = Signal()
    response_received = Signal(str, object)
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._port_name = ""
        self._baud_rate = 115200
        self._serial: serial.Serial | None = None
        self._running = False
        self._send_queue: deque[str] = deque(maxlen=200)
        self._mutex = QMutex()
        self._send_timeout = 2.0

    def open(self, port_name: str, baud_rate: int = 115200) -> None:
        """Queue a connection request. Actual open happens in run()."""
        if self.isRunning():
            logger.warning("SerialClient: already running, ignoring open()")
            return
        self._port_name = port_name
        self._baud_rate = baud_rate
        self._running = True
        self.start()

    def close(self) -> None:
        """Disconnect and stop the worker thread."""
        self._running = False
        if self.isRunning():
            self.wait(3000)

    def send(self, cmd: str) -> None:
        """Enqueue a command for sending (without braces)."""
        if not cmd or not isinstance(cmd, str):
            return
        with QMutexLocker(self._mutex):
            self._send_queue.append(cmd)

    def send_urgent(self, cmd: str) -> None:
        """Enqueue a command at the front (e.g. STOP)."""
        if not cmd or not isinstance(cmd, str):
            return
        with QMutexLocker(self._mutex):
            self._send_queue.appendleft(cmd)

    def queue_size(self) -> int:
        """Return the number of pending commands."""
        with QMutexLocker(self._mutex):
            return len(self._send_queue)

    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def _wait_ready(self, timeout: float = 10.0) -> bool:
        """Actively probe Arduino to verify it's alive.

        Leonardo resets on serial open. The READY line from setup() is often
        lost during USB re-enumeration. Instead, we wait for the reset cycle,
        then send a PING probe and check for the CMD:PING echo response.
        """
        import time as _time
        from .serial_protocol import encode_command

        # Wait for Leonardo reset cycle to complete
        _time.sleep(3.5)

        deadline = _time.monotonic() + timeout
        while _time.monotonic() < deadline:
            if self._serial is None or not self._serial.is_open:
                return False

            # Flush stale data
            try:
                while self._serial.in_waiting:
                    self._serial.readline()
            except Exception:
                pass

            # Send probe and check for echo
            try:
                self._serial.write(encode_command("PING"))
                self._serial.flush()
                _time.sleep(0.15)
                if self._serial.in_waiting:
                    line_bytes = self._serial.readline()
                    try:
                        line = line_bytes.decode("utf-8", errors="replace").strip()
                    except UnicodeDecodeError:
                        line = line_bytes.decode("latin-1", errors="replace").strip()
                    if "PING" in line or "READY" in line or "CMD" in line:
                        logger.info("Arduino handshake OK on %s", self._port_name)
                        return True
            except serial.SerialException:
                pass

            _time.sleep(0.5)

        logger.warning("Arduino handshake timeout on %s after %.1fs",
                        self._port_name, timeout)
        return False

    def run(self) -> None:
        """Main worker loop. Opens serial and processes send/receive."""
        # ── Open ──
        try:
            self._serial = serial.Serial(
                port=self._port_name,
                baudrate=self._baud_rate,
                timeout=0.1,
                write_timeout=0.5,
            )
            # CRITICAL: disable DTR to prevent Leonardo auto-reset loop
            # (opening the port already triggered one reset, which is fine)
            self._serial.dtr = False

            # Handshake: actively probe Arduino with PING command
            ready = self._wait_ready(timeout=10.0)
            if not ready:
                self.error_occurred.emit(
                    f"Arduino did not respond on {self._port_name} — check firmware"
                )
                self._serial.close()
                self._serial = None
                self._running = False
                self.disconnected.emit()
                return
            self.connected.emit(self._port_name)
        except serial.SerialException as e:
            self.error_occurred.emit(f"Failed to open {self._port_name}: {e}")
            self._running = False
            self._serial = None
            self.disconnected.emit()  # ensure UI state consistency
            return
        except Exception as e:
            self.error_occurred.emit(f"Unexpected error opening port: {e}")
            self._running = False
            self._serial = None
            self.disconnected.emit()
            return

        # ── Main loop ──
        while self._running:
            try:
                # Send pending commands
                with QMutexLocker(self._mutex):
                    if self._send_queue:
                        cmd = self._send_queue.popleft()
                        wire = encode_command(cmd)
                        self._serial.write(wire)
                        self._serial.flush()

                # Read response
                if self._serial.in_waiting:
                    line_bytes = self._serial.readline()
                    try:
                        line = line_bytes.decode("utf-8", errors="replace").strip()
                    except UnicodeDecodeError:
                        line = line_bytes.decode("latin-1", errors="replace").strip()
                    if line:
                        resp_type, payload = decode_response(line)
                        self.response_received.emit(resp_type, payload)
            except serial.SerialException as e:
                self.error_occurred.emit(f"Serial error: {e}")
                break
            except Exception as e:
                self.error_occurred.emit(f"Unexpected error: {e}")
                break  # break on generic errors too — don't spin-forever

        # ── Cleanup ──
        if self._serial is not None:
            try:
                if self._serial.is_open:
                    self._serial.close()
            except serial.SerialException as e:
                logger.warning("Error closing serial port: %s", e)
            except Exception:
                pass
            self._serial = None
        self.disconnected.emit()
