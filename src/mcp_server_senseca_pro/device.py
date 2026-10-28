"""Serial driver for Senseca PRO 111 / PRO 115 Pt100 thermometers.

The instrument shows up as a USB CDC virtual COM port (115200 8N1). Commands are
ASCII lines of the form ``Command: argument`` terminated by CRLF; every reply is
one or more CRLF-terminated lines followed by an empty line.

This module does not depend on MCP so it can be used and tested on its own.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

import serial
from serial.tools import list_ports

log = logging.getLogger(__name__)

BAUDRATE = 115200
# Generic STMicroelectronics Virtual COM Port ID. Many other devices use it too,
# so candidates are only accepted after the manufacturer query answers "senseca".
USB_VID = 0x0483
USB_PID = 0x5740

REPLY_TERMINATOR = b"\r\n\r\n"

# Channel layout observed on PRO 111 firmware V1.4.3.0.
BATTERY_CHANNEL = (0, None)
RESISTANCE_CHANNEL = (1, None)
TEMPERATURE_CHANNEL = (1, 1)

# The serial interface relocks after 2 minutes without commands; resend the PIN before that.
PIN_REFRESH_S = 90.0

_RANGE_STATES = {"underflow", "overflow"}
_DATETIME_RE = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:\.(\d+))?")


class DeviceError(Exception):
    """Base class for all errors raised by this module."""


class DeviceNotFoundError(DeviceError):
    pass


class CommandError(DeviceError):
    """The instrument answered with ``error: ...``."""


class OutOfRangeError(DeviceError):
    """The instrument reported Underflow/Overflow, e.g. no probe connected."""


class SerialLike(Protocol):
    def write(self, data: bytes) -> int | None: ...
    def read_until(self, expected: bytes = ..., size: int | None = ...) -> bytes: ...
    def reset_input_buffer(self) -> None: ...
    def reset_output_buffer(self) -> None: ...
    def close(self) -> None: ...


Opener = Callable[[str], SerialLike]


def _open_serial(port: str) -> serial.Serial:
    return serial.Serial(port, BAUDRATE, timeout=2.0, write_timeout=2.0, exclusive=True)


@dataclass(frozen=True)
class Reading:
    value: float
    unit: str
    timestamp: datetime

    def as_dict(self) -> dict[str, Any]:
        return {"value": self.value, "unit": self.unit, "timestamp": self.timestamp.isoformat()}


class Pro11x:
    """Thread-safe connection to one PRO 11x instrument.

    The port is opened lazily and reopened once if a command fails because the
    device was unplugged or switched off in the meantime.
    """

    def __init__(self, port: str | None = None, pin: str | None = None, opener: Opener = _open_serial):
        self._port = port
        # An auto-detected port is searched again after a disconnect, since the
        # instrument may come back under a different device name.
        self._auto_detect = port is None
        self._pin = f"{int(pin):04d}" if pin else None
        self._opener = opener
        self._conn: SerialLike | None = None
        self._lock = threading.Lock()
        self._last_command = 0.0

    @property
    def port(self) -> str | None:
        return self._port

    def close(self) -> None:
        with self._lock:
            self._disconnect()

    def __enter__(self) -> Pro11x:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- low level -----------------------------------------------------------

    def query(self, command: str) -> list[str]:
        """Send one command and return the non-empty reply lines."""
        with self._lock:
            try:
                return self._query_locked(command)
            except serial.SerialTimeoutException as e:
                # The port is fine but the firmware does not take data; reopening will not help.
                self._disconnect()
                raise DeviceError(
                    f"Instrument on {self._port} does not respond. Check that it is switched on; "
                    "if it is, unplug and reconnect the USB cable."
                ) from e
            except (serial.SerialException, OSError) as e:
                log.warning("Serial error (%s), reconnecting", e)
                self._disconnect()
                try:
                    return self._query_locked(command)
                except (serial.SerialException, OSError) as e2:
                    self._disconnect()
                    raise DeviceError(f"Communication with {self._port} failed: {e2}") from e2

    def _query_locked(self, command: str) -> list[str]:
        conn = self._connect()
        if self._pin and time.monotonic() - self._last_command > PIN_REFRESH_S:
            self._exchange(conn, f"setPINCode: {self._pin}")
        return self._exchange(conn, command)

    def _exchange(self, conn: SerialLike, command: str) -> list[str]:
        conn.reset_input_buffer()
        conn.write(command.encode("ascii") + b"\r\n")
        raw = conn.read_until(REPLY_TERMINATOR)
        self._last_command = time.monotonic()
        if not raw.endswith(REPLY_TERMINATOR):
            raise DeviceError(f"Timeout waiting for reply to {command!r} (got {raw!r})")
        lines = [line.strip() for line in raw.decode("utf-8", errors="replace").splitlines()]
        lines = [line for line in lines if line]
        if lines and lines[0].lower().startswith("error:"):
            raise CommandError(f"{command!r}: {lines[0][6:].strip()}")
        return lines

    def _connect(self) -> SerialLike:
        if self._conn is None:
            if self._port is None:
                self._port = find_port(self._opener)
            log.info("Opening %s", self._port)
            try:
                self._conn = self._opener(self._port)
            except (serial.SerialException, OSError) as e:
                raise DeviceNotFoundError(f"Cannot open {self._port}: {e}") from e
            self._last_command = 0.0
        return self._conn

    def _disconnect(self) -> None:
        if self._conn is not None:
            try:
                # Drop unsent data, otherwise close() blocks up to 30 s (tty closing_wait).
                self._conn.reset_output_buffer()
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        if self._auto_detect:
            self._port = None

    def _single(self, command: str) -> str:
        lines = self.query(command)
        if not lines:
            raise DeviceError(f"Empty reply to {command!r}")
        return lines[0]

    # -- commands ------------------------------------------------------------

    @staticmethod
    def _channel_arg(channel: int, sub: int | None) -> str:
        return f"{channel}" if sub is None else f"{channel}, {sub}"

    def value(self, channel: int, sub: int | None = None) -> float:
        """Latest measured value of a channel in full resolution."""
        text = self._single(f"GetFullResolutionValue: {self._channel_arg(channel, sub)}")
        if text.lower() in _RANGE_STATES:
            raise OutOfRangeError(f"Measurement {text} (probe missing, broken or out of range)")
        try:
            return float(text)
        except ValueError:
            raise DeviceError(f"Unexpected measurement reply: {text!r}") from None

    def unit(self, channel: int, sub: int | None = None) -> str:
        return self._single(f"GetChannelUnit: {self._channel_arg(channel, sub)}")

    def reading(self, channel: int, sub: int | None = None) -> Reading:
        return Reading(self.value(channel, sub), self.unit(channel, sub), datetime.now(timezone.utc))

    def temperature(self) -> Reading:
        return self.reading(*TEMPERATURE_CHANNEL)

    def resistance(self) -> Reading:
        return self.reading(*RESISTANCE_CHANNEL)

    def battery(self) -> Reading:
        return self.reading(*BATTERY_CHANNEL)

    def manufacturer(self) -> str:
        return self._single("GetDeviceManufacturer: 0")

    def device_information(self) -> dict[str, str]:
        info: dict[str, str] = {}
        for line in self.query("GetDeviceInformation: 0"):
            key, sep, value = line.partition(":")
            if sep:
                info[key.strip().strip('"')] = value.strip().strip('"')
        return info

    def get_datetime(self) -> datetime:
        """Instrument clock (the instrument keeps UTC)."""
        text = self._single("GetDateTime: 0")
        m = _DATETIME_RE.search(text)
        if not m:
            raise DeviceError(f"Unexpected date/time reply: {text!r}")
        # Pad the fraction ("08.55") to microseconds; Python 3.10 only parses 3 or 6 digits.
        fraction = (m.group(2) or "").ljust(6, "0")[:6]
        return datetime.fromisoformat(f"{m.group(1)}.{fraction}").replace(tzinfo=timezone.utc)

    def set_datetime(self, when: datetime) -> list[str]:
        utc = when.astimezone(timezone.utc) if when.tzinfo else when
        return self.query(f"SetDateTime: {utc:%Y-%m-%d %H:%M:%S}")

    def update_location(self, index: int, name: str) -> list[str]:
        if not 1 <= index <= 20:
            raise ValueError("Location index must be 1..20")
        if len(name) > 16 or not name.isascii() or any(c in name for c in "\r\n"):
            raise ValueError("Location name must be at most 16 ASCII characters on one line")
        return self.query(f"updateLocation: {index}, {name}")


def find_port(opener: Opener = _open_serial) -> str:
    """Return the first serial port that answers like a Senseca instrument."""
    candidates = [p.device for p in list_ports.comports() if p.vid == USB_VID and p.pid == USB_PID]
    if not candidates:
        raise DeviceNotFoundError(
            "No Senseca instrument found. Check the USB cable, that the instrument is on, "
            "and set SENSECA_PORT if auto-detection does not work."
        )
    problems = []
    for device in candidates:
        probe = Pro11x(device, opener=opener)
        try:
            manufacturer = probe.manufacturer()
            if manufacturer.lower() == "senseca":
                return device
            problems.append(f"{device}: manufacturer is {manufacturer!r}")
        except DeviceError as e:
            problems.append(str(e))
        finally:
            probe.close()
    raise DeviceNotFoundError("No Senseca instrument answered. " + " ".join(problems))
