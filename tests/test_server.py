import pytest
from mcp import Client

from mcp_server_senseca_pro.server import create_server

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_read_only_by_default(device):
    async with Client(create_server(device)) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert names == {"read_temperature", "read_resistance", "sample_temperature", "get_device_info"}


async def test_write_tools_need_flag(device):
    async with Client(create_server(device, allow_write=True)) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert {"set_device_clock", "set_location_name"} <= names


async def test_read_temperature(device):
    async with Client(create_server(device)) as client:
        result = await client.call_tool("read_temperature", {})
    assert not result.is_error
    assert result.structured_content["value"] == 22.63
    assert result.structured_content["unit"] == "°C"


async def test_sample_temperature(device):
    async with Client(create_server(device)) as client:
        result = await client.call_tool("sample_temperature", {"duration_s": 1, "interval_s": 0.5})
    data = result.structured_content
    assert data["count"] == 3
    assert data["min"] == data["max"] == data["mean"] == 22.63


async def test_sample_rejects_too_fast_interval(device):
    async with Client(create_server(device)) as client:
        result = await client.call_tool("sample_temperature", {"duration_s": 1, "interval_s": 0.1})
    assert result.is_error
    assert "at least 0.5" in result.content[0].text


async def test_device_error_reaches_model(device, fake):
    fake.replies["GetFullResolutionValue: 1, 1"] = "Underflow"
    async with Client(create_server(device)) as client:
        result = await client.call_tool("read_temperature", {})
    assert result.is_error
    assert "Underflow" in result.content[0].text


async def test_get_device_info(device):
    async with Client(create_server(device)) as client:
        result = await client.call_tool("get_device_info", {})
    data = result.structured_content
    assert data["S/N"] == "P1100001"
    assert data["battery_percent"] == 100.0
    assert data["clock_utc"].startswith("2026-10-28T17:51:08")
