"""Check a connected Senseca PRO 11x instrument against this server.

Run from the repository root:

    uv run python scripts/hardware_test.py [--port PORT] [--pin PIN] [--reconnect] [--pin-idle]

Only read commands are sent. The basic checks need no interaction. The optional
tests need you at the instrument:

    --reconnect  unplug USB and plug it back in while readings run (60 s)
    --pin-idle   with PIN protection enabled: waits 130 s to check that the PIN is resent

Exit code 0 if all checks passed.
"""

import argparse
import os
import statistics
import sys
import time
from datetime import datetime, timezone

import anyio
from mcp import Client

from mcp_server_senseca_pro.device import DeviceError, Pro11x
from mcp_server_senseca_pro.server import create_server

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    failures += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{': ' + detail if detail else ''}", flush=True)


def basic(device: Pro11x) -> None:
    info = device.device_information()
    check("device information", "Device" in info, f"{info.get('Device')}, firmware {info.get('Version')}, port {device.port}")

    t = device.temperature()
    check("temperature", t.unit in ("°C", "°F", "K"), f"{t.value} {t.unit}")
    r = device.resistance()
    check("resistance", r.unit == "ohm" and 15 < r.value < 400, f"{r.value} {r.unit}")
    b = device.battery()
    check("battery level", b.unit == "%" and 0 <= b.value <= 100, f"{b.value} {b.unit}")

    drift = (device.get_datetime() - datetime.now(timezone.utc)).total_seconds()
    check("instrument clock", abs(drift) < 60, f"{drift:+.1f} s compared to this computer")

    values = []
    for _ in range(6):
        values.append(device.temperature().value)
        time.sleep(0.5)
    check("6 readings in 3 s", len(values) == 6, f"min {min(values)}, max {max(values)}, stdev {statistics.stdev(values):.3f}")


async def mcp_layer(device: Pro11x) -> None:
    async with Client(create_server(device)) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        check("MCP tools listed", "read_temperature" in tools, ", ".join(sorted(tools)))
        result = await client.call_tool("read_temperature", {})
        detail = result.content[0].text if result.is_error else str(result.structured_content["value"])
        check("MCP read_temperature", not result.is_error, detail)


def reconnect(device: Pro11x) -> None:
    print("Unplug USB within the next 20 s, wait a few seconds, then plug it back in.", flush=True)
    saw_error = recovered = False
    end = time.monotonic() + 60
    while time.monotonic() < end and not recovered:
        try:
            reading = device.temperature()
            print(f"  {reading.value} {reading.unit}", flush=True)
            recovered = saw_error
        except DeviceError as e:
            print(f"  error: {e}", flush=True)
            saw_error = True
        time.sleep(1)
    check("reconnect after unplug", recovered, "" if saw_error else "USB was not unplugged")


def pin_idle(device: Pro11x) -> None:
    device.temperature()
    for left in range(130, 0, -10):
        print(f"  idle, {left} s left", flush=True)
        time.sleep(10)
    try:
        detail = f"{device.temperature().value} after 130 s idle"
        check("PIN resent after idle", True, detail)
    except DeviceError as e:
        check("PIN resent after idle", False, str(e))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", default=os.environ.get("SENSECA_PORT"))
    parser.add_argument("--pin", default=os.environ.get("SENSECA_PIN"))
    parser.add_argument("--reconnect", action="store_true")
    parser.add_argument("--pin-idle", action="store_true")
    args = parser.parse_args()
    if args.pin_idle and not args.pin:
        parser.error("--pin-idle needs --pin or SENSECA_PIN")

    with Pro11x(port=args.port, pin=args.pin) as device:
        try:
            basic(device)
            anyio.run(mcp_layer, device)
            if args.reconnect:
                reconnect(device)
            if args.pin_idle:
                pin_idle(device)
        except DeviceError as e:
            check("communication", False, str(e))

    print(f"\n{'All checks passed.' if not failures else f'{failures} check(s) failed.'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
