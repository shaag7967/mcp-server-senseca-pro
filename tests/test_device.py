from datetime import datetime, timezone

import pytest
import serial

from mcp_server_senseca_pro.device import CommandError, DeviceError, OutOfRangeError, Pro11x


def test_temperature(device):
    reading = device.temperature()
    assert reading.value == 22.63
    assert reading.unit == "°C"


def test_resistance(device):
    reading = device.resistance()
    assert reading.value == 108.815
    assert reading.unit == "ohm"


def test_underflow_raises(device):
    with pytest.raises(OutOfRangeError, match="Underflow"):
        device.value(1, 2)


def test_error_reply_raises(device):
    with pytest.raises(CommandError, match="out of range"):
        device.value(5)


def test_device_information(device):
    info = device.device_information()
    assert info["Device"] == "PRO 111"
    assert info["S/N"] == "P1100001"
    assert info["Type"] == "PRO 110"
    assert info["Operating System"] == "ThreadX  6.1.8"
    assert info["GUID"] == "{0000::0000::0000::0000::0000::0001}"


def test_datetime_with_unbalanced_quotes(device):
    assert device.get_datetime() == datetime(2026, 10, 28, 17, 51, 8, 550000, tzinfo=timezone.utc)


def test_set_datetime_converts_to_utc(device, fake):
    fake.replies["SetDateTime: 2026-10-28 17:00:00"] = "OK"
    local = datetime.fromisoformat("2026-10-28T18:00:00+01:00")
    device.set_datetime(local)
    assert fake.sent[-1] == "SetDateTime: 2026-10-28 17:00:00"


@pytest.mark.parametrize("name", ["x" * 17, "Labor\r\nSetDateTime", "Prüfstand"])
def test_update_location_rejects_bad_names(device, fake, name):
    with pytest.raises(ValueError):
        device.update_location(1, name)
    assert fake.sent == []


def test_pin_sent_before_first_command(fake):
    fake.replies["setPINCode: 0023"] = "OK"
    device = Pro11x("/dev/fake", pin="23", opener=lambda port: fake)
    device.temperature()
    assert fake.sent[0] == "setPINCode: 0023"
    assert fake.sent.count("setPINCode: 0023") == 1


def test_pin_sent_shortly_after_boot(fake, monkeypatch):
    # time.monotonic() counts from system start, so it can be small on a fresh machine.
    monkeypatch.setattr("mcp_server_senseca_pro.device.time.monotonic", lambda: 5.0)
    fake.replies["setPINCode: 0023"] = "OK"
    device = Pro11x("/dev/fake", pin="23", opener=lambda port: fake)
    device.temperature()
    assert fake.sent[0] == "setPINCode: 0023"


def test_reconnects_once_after_serial_error(fake):
    opened = []

    class Flaky:
        def write(self, data):
            raise serial.SerialException("device disconnected")

        def reset_input_buffer(self):
            pass

        def reset_output_buffer(self):
            pass

        def close(self):
            pass

    def opener(port):
        opened.append(port)
        return Flaky() if len(opened) == 1 else fake

    device = Pro11x("/dev/fake", opener=opener)
    assert device.temperature().value == 22.63
    assert len(opened) == 2


def test_timeout_without_reply(fake):
    fake.read_until = lambda *a, **k: b"22.6"
    device = Pro11x("/dev/fake", opener=lambda port: fake)
    with pytest.raises(DeviceError, match="Timeout"):
        device.temperature()
