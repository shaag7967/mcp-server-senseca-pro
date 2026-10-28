# PRO 11x serial protocol

Observed on a PRO 111, firmware V1.4.3.0, interface protocol V1.0.0.1. The manual only documents
the transport; the command list comes from `GetCommandList: 0` (full text in
[command-list.txt](command-list.txt)).

## Transport

- USB CDC ACM, USB ID `0483:5740` (generic STMicroelectronics Virtual COM Port)
- 115200 baud, 8 data bits, no parity, 1 stop bit
- Command: `Name: argument` followed by CRLF. A space after the colon is required.
- Reply: one or more lines, each ending with CRLF, followed by an empty line (`\r\n\r\n`).
- Errors are returned as a line starting with `error:`.

## Channels

| Channel | Unit | Meaning |
|---|---|---|
| `0` | `%` | battery level; reads 0.0 with batteries removed, also while powered via USB |
| `1` | `ohm` | Pt100 resistance |
| `1, 1` | `°C` (or the unit set on the instrument) | temperature |

`GetFullResolutionValue` returns more digits than `GetLastValue` (`108.815` vs. `108.81`).
Values are left-padded with spaces. Instead of a number the reply can be `Underflow` or `Overflow`.

## Replies

| Command | Example reply |
|---|---|
| `GetDeviceIdentification: 0` | `P1100001` |
| `GetDeviceType: 0` | `PRO 111` |
| `GetDeviceManufacturer: 0` | `senseca` |
| `GetFullResolutionValue: 1, 1` | `           22.63` |
| `GetChannelUnit: 1, 1` | `°C` |
| `GetDateTime: 0` | `"Time (UTC)": 2026-10-28 17:51:08.55"` (quotes are unbalanced) |
| `GetCalibrationReport: 1` | `error: not available` |
| `GetDeviceInformation: 0` | several `Key: value` lines, keys and values sometimes in quotes |

## Known firmware problem

`GetCalibrationReport: 2` (a channel that does not exist) returns no reply and the instrument
freezes completely:

- the serial interface accepts no more data (writes time out)
- the display stops updating, the backlight stays on, the status LED is off
- no key works, including ON/OFF; unplugging USB changes nothing
- only removing the batteries (with USB unplugged) recovers it

`GetCalibrationReport: 0` correctly answers `error: parameter or index out of range` and
`GetCalibrationReport: 1` answers `error: not available`. Reproduced twice on a PRO 111 with
firmware V1.4.3.0, the second time as a single command right after a power cycle.
Do not send `GetCalibrationReport` with invalid channel numbers. This server does not use the
command.

## Protected mode

When the instrument's PIN protection is on, every command is answered with

```
error: enter PIN with command "setPINCode: 0000" with your PIN for 0000 first!
```

(only observed with PIN 0000, so it is unknown whether the text shows the actual PIN or is
fixed). `setPINCode: nnnn` (always four
digits) answers `OK` and unlocks the interface. According to the manual it locks again after
2 minutes without commands; the driver resends the PIN after 90 s of inactivity. Tested on a
PRO 111 with PIN 0000, including a read after 130 s idle.
