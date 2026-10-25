"""Common fixtures for the Fairland (Modbus) tests."""

from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fairland_modbus.heat_pump.testing import HEATING, load_image
from modbus_connection import ModbusTcpParams
from modbus_connection.mock import MockModbusConnection, MockModbusUnit
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion

from custom_components.fairland_modbus.const import DOMAIN
from homeassistant.core import HomeAssistant

from . import MOCK_ENTRY_ID, MOCK_TCP_DATA, MOCK_TITLE


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from custom_components."""


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Serialize snapshots the way Home Assistant does."""
    return snapshot.use_extension(HomeAssistantSnapshotExtension)


@pytest.fixture(autouse=True)
def no_working_mode_settle() -> Generator[None]:
    """Read the working mode back without the pause a real board needs."""
    with patch(
        "fairland_modbus.heat_pump.device.WORKING_MODE_SETTLE",
        0,
    ):
        yield


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Override async_setup_entry."""
    with patch(
        "custom_components.fairland_modbus.async_setup_entry",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_setup_entry:
        yield mock_setup_entry


@pytest.fixture
def register_image(request: pytest.FixtureRequest) -> dict[str, dict[int, Any]]:
    """The registers the mock heat pump answers with."""
    return getattr(request, "param", HEATING)


@pytest.fixture
def entry_data(request: pytest.FixtureRequest) -> dict[str, Any]:
    """The data of the mock config entry."""
    return getattr(request, "param", MOCK_TCP_DATA)


@pytest.fixture
def mock_connection(register_image: dict[str, dict[int, Any]]) -> MockModbusConnection:
    """A fake Modbus link with the heat pump at address 1."""
    connection = MockModbusConnection()
    load_image(connection.for_unit(1), register_image)
    return connection


@pytest.fixture
def mock_unit(mock_connection: MockModbusConnection) -> MockModbusUnit:
    """The mock heat pump at address 1."""
    return mock_connection.for_unit(1)


@pytest.fixture
def mock_get_unit(mock_connection: MockModbusConnection) -> Generator[MagicMock]:
    """Hand the integration a unit on the mock connection."""
    with patch(
        "custom_components.fairland_modbus.async_get_unit",
        side_effect=lambda hass, entry, params, unit_id: mock_connection.for_unit(
            unit_id
        ),
    ) as mock_get_unit:
        yield mock_get_unit


@pytest.fixture
def mock_temporary_unit(
    mock_connection: MockModbusConnection,
) -> Generator[MagicMock]:
    """Hand the config flow a unit on the mock connection."""

    @asynccontextmanager
    async def _get_unit(
        hass: HomeAssistant, params: ModbusTcpParams, unit_id: int
    ) -> AsyncIterator[MockModbusUnit]:
        yield mock_connection.for_unit(unit_id)

    with patch(
        "custom_components.fairland_modbus.config_flow.async_get_temporary_unit",
        side_effect=_get_unit,
    ) as mock_temporary_unit:
        yield mock_temporary_unit


@pytest.fixture
def mock_config_entry(entry_data: dict[str, Any]) -> MockConfigEntry:
    """A config entry for the mock heat pump."""
    return MockConfigEntry(
        domain=DOMAIN, entry_id=MOCK_ENTRY_ID, data=entry_data, title=MOCK_TITLE
    )


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_get_unit: MagicMock,
) -> MockConfigEntry:
    """Set up the integration with the mock heat pump."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return mock_config_entry
