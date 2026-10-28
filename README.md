# mcp-server-senseca-pro

An [MCP](https://modelcontextprotocol.io) server that lets AI assistants read live measurements
from a **Senseca PRO 111 / PRO 115** handheld Pt100 thermometer connected via USB.

> Unofficial project, not affiliated with or endorsed by Senseca.
> Tested with a PRO 111, firmware V1.4.3.0, interface protocol V1.0.0.1.

## Tools

| Tool | Description |
|---|---|
| `read_temperature` | Current temperature with unit (°C/°F/K, as set on the instrument) and UTC timestamp |
| `read_resistance` | Current Pt100 resistance in ohm |
| `sample_temperature` | Readings over a period (max 600 s, interval ≥ 0.5 s) with min/max/mean/stdev |
| `get_device_info` | Model, serial number, firmware, instrument clock, battery level |

With `--allow-write` two more tools are available:

| Tool | Description |
|---|---|
| `set_device_clock` | Set the instrument clock (default: this computer's time) |
| `set_location_name` | Rename one of the 20 location labels |

The server cannot change calibration or adjustment data; the instrument does not offer that
over its serial interface.

## Requirements

- Python ≥ 3.10 and [uv](https://docs.astral.sh/uv/)
- The instrument switched on and connected via USB-C. On the PRO 115 set
  *Settings → USB mode* to **COM interface**.
- **Linux:** your user must be in the `dialout` group (`sudo usermod -aG dialout $USER`, then log in again).
- **Windows / macOS:** no extra setup; the port shows up as `COMx` or `/dev/cu.usbmodem…`.

## Configuration

### Claude Code

```bash
claude mcp add senseca-pro -- uvx mcp-server-senseca-pro
```

### Claude Desktop and other clients

```json
{
  "mcpServers": {
    "senseca-pro": {
      "command": "uvx",
      "args": ["mcp-server-senseca-pro"]
    }
  }
}
```

### Options

| Option | Environment variable | Default |
|---|---|---|
| `--port PORT` | `SENSECA_PORT` | auto-detect |
| `--allow-write` | `SENSECA_ALLOW_WRITE=1` | off |
| `--log-level LEVEL` | `SENSECA_LOG_LEVEL` | `WARNING` |
| — | `SENSECA_PIN` | none; needed only if the instrument's protected mode is on |

Auto-detection looks for USB ID `0483:5740` and only accepts a port whose device reports
manufacturer `senseca`. If several instruments are connected, set the port explicitly; on Linux
prefer the stable `/dev/serial/by-id/…` path.

Only one program can use the serial port at a time. Close ProXware or terminal programs while
the server is running.

## Measurement notes

- Instrument accuracy: ±0.05 °C or ±0.06 % of reading (whichever is higher) ±1 digit, probe not included.
- The USB port is **not galvanically isolated**. With a probe touching a grounded medium, the
  USB connection can shift the reading. Compare readings with and without USB, and use a USB
  isolator if they differ (see the instrument manual, section 7.2).

## Development

```bash
uv sync
uv run pytest                                   # tests use a simulated instrument
npx @modelcontextprotocol/inspector uv run mcp-server-senseca-pro   # try the tools interactively
```

To check a real instrument, connect it and run:

```bash
uv run python scripts/hardware_test.py               # read-only checks, no interaction
uv run python scripts/hardware_test.py --reconnect   # also unplug/replug USB when asked
```

The script only sends read commands. See `--help` for the PIN test.

The serial protocol is described in [docs/protocol.md](https://github.com/shaag7967/mcp-server-senseca-pro/blob/main/docs/protocol.md).

## License

MIT

<!-- mcp-name: io.github.shaag7967/mcp-server-senseca-pro -->
