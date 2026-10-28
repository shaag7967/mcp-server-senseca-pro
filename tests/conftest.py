import pytest

from mcp_server_senseca_pro.device import Pro11x

# Replies recorded from a PRO 111 (firmware V1.4.3.0) on 2026-10-28.
RECORDED = {
    "GetDeviceIdentification: 0": "P1100001",
    "GetDeviceType: 0": "PRO 111",
    "GetDeviceManufacturer: 0": "senseca",
    "GetLastValue: 1": " 108.81",
    "GetFullResolutionValue: 0": "           100.0",
    "GetFullResolutionValue: 1": "         108.815",
    "GetFullResolutionValue: 1, 1": "           22.63",
    "GetFullResolutionValue: 1, 2": "Underflow",
    "GetChannelUnit: 0": "%",
    "GetChannelUnit: 1": "ohm",
    "GetChannelUnit: 1, 1": "°C",
    "GetDateTime: 0": '"Time (UTC)": 2026-10-28 17:51:08.55"',
    "GetCalibrationReport: 1": "error: not available",
    "GetDeviceInformation: 0": "\r\n".join(
        [
            "Device: PRO 111",
            'Type: "PRO 110"',
            "S/N: P1100001",
            "Version: V1.4.3.0",
            "From: 2026-03-18",
            "Manufacturer1: senseca",
            "Manufacturer2: makes sense",
            "GUID: {0000::0000::0000::0000::0000::0001}",
            '"Operating System": "ThreadX  6.1.8"',
            '"Interface protocol": V1.0.0.1',
        ]
    ),
}


LOCKED_REPLY = 'error: enter PIN with command "setPINCode: 0000" with your PIN for 0000 first!'


class FakeSerial:
    """Stands in for serial.Serial and answers like the instrument.

    With ``pin`` set it behaves like an instrument in protected mode.
    """

    def __init__(self, replies: dict[str, str], pin: str | None = None):
        self.replies = dict(replies)
        self.pin = pin
        self.sent: list[str] = []
        self.closed = False
        self._pending = b""

    def write(self, data: bytes) -> int:
        command = data.decode().removesuffix("\r\n")
        self.sent.append(command)
        if self.pin and command == f"setPINCode: {self.pin}":
            self.pin = None
            reply = "OK"
        elif self.pin:
            reply = LOCKED_REPLY
        else:
            reply = self.replies.get(command, "error: parameter or index out of range")
        self._pending = reply.encode() + b"\r\n\r\n"
        return len(data)

    def read_until(self, expected: bytes = b"\n", size: int | None = None) -> bytes:
        out, self._pending = self._pending, b""
        return out

    def reset_input_buffer(self) -> None:
        pass

    def reset_output_buffer(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake() -> FakeSerial:
    return FakeSerial(RECORDED)


@pytest.fixture
def device(fake: FakeSerial) -> Pro11x:
    return Pro11x("/dev/fake", opener=lambda port: fake)


@pytest.fixture
def locked() -> FakeSerial:
    return FakeSerial(RECORDED, pin="0000")
