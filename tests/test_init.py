"""Tests for setting up and polling the Fairland (Modbus) integration."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from modbus_connection import (
    GatewayTargetError,
    IllegalDataAddressError,
    ModbusConnectionError,
    ModbusTimeoutError,
)
from modbus_connection.mock import MockModbusConnection, MockModbusUnit
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.fairland_modbus.const import DOMAIN, UPDATE_INTERVAL
from homeassistant.components.climate import ATTR_CURRENT_TEMPERATURE, ATTR_HVAC_ACTION
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

CLIMATE = "climate.fairland_heat_pump"


async def _poll(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Let the coordinator poll once."""
    freezer.tick(UPDATE_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_setup_and_unload(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test the entry loads, reads the heat pump, and unloads."""
    assert init_integration.state is ConfigEntryState.LOADED
    assert hass.states.get(CLIMATE).attributes[ATTR_CURRENT_TEMPERATURE] == 26.0
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, init_integration.entry_id), init_integration.entry_id
    )
    assert device is not None
    assert device.manufacturer == "Fairland"

    await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    assert init_integration.state is ConfigEntryState.NOT_LOADED


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(ModbusConnectionError(), id="unreachable"),
        pytest.param(ModbusTimeoutError(), id="silent"),
        pytest.param(GatewayTargetError(), id="silent_behind_gateway"),
    ],
)
@pytest.mark.usefixtures("mock_get_unit")
async def test_setup_retries_while_the_heat_pump_is_unreachable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_unit: MockModbusUnit,
    error: Exception,
) -> None:
    """Test setup is retried until the heat pump answers."""
    mock_unit.fail_requests(error)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.usefixtures("mock_get_unit")
async def test_setup_retries_when_every_block_is_refused(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_unit: MockModbusUnit,
) -> None:
    """Test a device that refuses every block is not set up."""
    mock_unit.fail_requests(IllegalDataAddressError())
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_failing_block_only_affects_what_uses_it(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test a block that stops answering, then recovers."""
    mock_unit.fail_read(0, IllegalDataAddressError(), register_type="discrete")
    await _poll(hass, freezer)
    state = hass.states.get(CLIMATE)
    assert state.state == "heat"
    assert state.attributes.get(ATTR_HVAC_ACTION) is None
    assert "status failed to refresh" in caplog.text

    mock_unit.fail_read(0, None, register_type="discrete")
    await _poll(hass, freezer)
    assert hass.states.get(CLIMATE).attributes[ATTR_HVAC_ACTION] == "heating"
    assert "status is available again" in caplog.text


async def test_heat_pump_going_offline(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test the entity goes unavailable while the link is down, then comes back."""
    mock_unit.fail_requests(ModbusConnectionError())
    await _poll(hass, freezer)
    assert hass.states.get(CLIMATE).state == STATE_UNAVAILABLE

    mock_unit.fail_requests(None)
    mock_unit.input[3] = 116
    await _poll(hass, freezer)
    assert hass.states.get(CLIMATE).attributes[ATTR_CURRENT_TEMPERATURE] == 28.0


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(ModbusTimeoutError(), id="timeout"),
        pytest.param(GatewayTargetError(), id="gateway_target_failed"),
    ],
)
async def test_silent_heat_pump_keeps_the_shared_link(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_connection: MockModbusConnection,
    mock_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
    error: Exception,
) -> None:
    """Test a silent heat pump does not drop a link other devices may share."""
    mock_unit.fail_requests(error)
    for _ in range(5):
        await _poll(hass, freezer)
    assert mock_connection.connected
    assert hass.states.get(CLIMATE).state == STATE_UNAVAILABLE

    mock_unit.fail_requests(None)
    await _poll(hass, freezer)
    assert hass.states.get(CLIMATE).state == "heat"


async def test_every_block_refused_marks_the_entity_unavailable(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a poll where every block is refused."""
    mock_unit.fail_requests(IllegalDataAddressError())
    await _poll(hass, freezer)
    assert hass.states.get(CLIMATE).state == STATE_UNAVAILABLE
