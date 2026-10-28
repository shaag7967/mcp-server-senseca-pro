"""MCP server exposing a Senseca PRO 111 / PRO 115 thermometer."""

import argparse
import logging
import os
import statistics
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.metadata import version
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from .device import DeviceError, Pro11x

log = logging.getLogger(__name__)

ACCURACY = "±0.05 °C or ±0.06 % of reading (whichever is higher) ±1 digit, instrument only"
MIN_INTERVAL_S = 0.5  # the instrument measures 2 times per second
MAX_DURATION_S = 600.0

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)
WRITES_DEVICE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)

INSTRUCTIONS = """\
Access to a Senseca PRO 111/115 handheld thermometer with a 4-wire Pt100 probe, connected via USB.
Readings are live values from the physical instrument. The temperature unit follows the instrument
setting (°C, °F or K) and is always returned with the value. The instrument updates twice per second.
"""


@contextmanager
def _device_errors() -> Iterator[None]:
    # Only ToolError messages reach the model; anything else shows up as a bare crash.
    try:
        yield
    except (DeviceError, ValueError) as e:
        raise ToolError(str(e)) from e


def create_server(device: Pro11x, allow_write: bool = False) -> MCPServer:
    mcp = MCPServer(
        name="senseca-pro",
        title="Senseca PRO 111/115 thermometer",
        version=version("mcp-server-senseca-pro"),
        instructions=INSTRUCTIONS,
    )

    @mcp.tool(annotations=READ_ONLY)
    def read_temperature() -> dict[str, Any]:
        """Read the current temperature from the Pt100 probe, with unit and UTC timestamp."""
        with _device_errors():
            return device.temperature().as_dict() | {"accuracy": ACCURACY}

    @mcp.tool(annotations=READ_ONLY)
    def read_resistance() -> dict[str, Any]:
        """Read the current Pt100 probe resistance in ohm (about 100 ohm at 0 °C)."""
        with _device_errors():
            return device.resistance().as_dict()

    @mcp.tool(annotations=READ_ONLY)
    def sample_temperature(duration_s: float = 10.0, interval_s: float = 1.0) -> dict[str, Any]:
        """Record temperature readings over a period and return statistics plus all samples.

        Args:
            duration_s: Recording time in seconds (max 600).
            interval_s: Time between readings in seconds (min 0.5, the instrument's update rate).
        """
        if not 0 < duration_s <= MAX_DURATION_S:
            raise ToolError(f"duration_s must be between 0 and {MAX_DURATION_S:g}")
        if interval_s < MIN_INTERVAL_S:
            raise ToolError(f"interval_s must be at least {MIN_INTERVAL_S}")
        samples = []
        with _device_errors():
            start = time.monotonic()
            while True:
                samples.append(device.temperature())
                next_at = start + len(samples) * interval_s
                if next_at - start > duration_s:
                    break
                time.sleep(max(0.0, next_at - time.monotonic()))
        values = [s.value for s in samples]
        return {
            "unit": samples[0].unit,
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "mean": round(statistics.fmean(values), 4),
            "stdev": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
            "start": samples[0].timestamp.isoformat(),
            "end": samples[-1].timestamp.isoformat(),
            "samples": [{"t": s.timestamp.isoformat(), "value": s.value} for s in samples],
        }

    @mcp.tool(annotations=READ_ONLY)
    def get_device_info() -> dict[str, Any]:
        """Instrument model, serial number, firmware, clock (UTC) and battery level."""
        with _device_errors():
            info: dict[str, Any] = dict(device.device_information())
            info["port"] = device.port
            info["clock_utc"] = device.get_datetime().isoformat()
            info["battery_percent"] = device.battery().value
            return info

    if allow_write:

        @mcp.tool(annotations=WRITES_DEVICE)
        def set_device_clock(utc_time: str | None = None) -> dict[str, Any]:
            """Set the instrument clock. Without argument it is synchronised to this computer's time.

            Args:
                utc_time: Optional ISO 8601 time, e.g. "2026-10-28 17:00:00" (interpreted as UTC).
            """
            with _device_errors():
                when = datetime.fromisoformat(utc_time) if utc_time else datetime.now(timezone.utc)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                device.set_datetime(when)
                return {"clock_utc": device.get_datetime().isoformat()}

        @mcp.tool(annotations=WRITES_DEVICE)
        def set_location_name(index: int, name: str) -> dict[str, Any]:
            """Rename one of the 20 location labels used when saving single readings on the instrument.

            Args:
                index: Label number 1..20.
                name: New label text, at most 16 ASCII characters.
            """
            with _device_errors():
                reply = device.update_location(index, name)
                return {"index": index, "name": name, "reply": reply}

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(prog="mcp-server-senseca-pro", description=__doc__)
    parser.add_argument(
        "--port",
        default=os.environ.get("SENSECA_PORT"),
        help="serial port, e.g. /dev/ttyACM0 or COM3 (env SENSECA_PORT; default: auto-detect)",
    )
    parser.add_argument(
        "--allow-write",
        action="store_true",
        default=os.environ.get("SENSECA_ALLOW_WRITE", "").lower() in ("1", "true", "yes"),
        help="enable tools that change instrument settings (env SENSECA_ALLOW_WRITE)",
    )
    parser.add_argument("--log-level", default=os.environ.get("SENSECA_LOG_LEVEL", "WARNING"))
    args = parser.parse_args()

    # stdout carries the MCP protocol, so logs must go to stderr.
    logging.basicConfig(stream=sys.stderr, level=args.log_level.upper(), format="%(levelname)s %(name)s: %(message)s")

    # The PIN is only read from the environment so it never ends up in a process list or chat.
    device = Pro11x(port=args.port, pin=os.environ.get("SENSECA_PIN"))
    try:
        create_server(device, allow_write=args.allow_write).run("stdio")
    finally:
        device.close()
