"""Tests for the Fairland (Modbus) sensors."""

from datetime import timedelta

from fairland_modbus.heat_pump.testing import HEATING
from freezegun.api import FrozenDateTimeFactory
from modbus_connection import IllegalDataAddressError
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant.common import (
    MockConfigEntry,
    async_fire_time_changed,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

from custom_components.fairland_modbus.const import UPDATE_INTERVAL
from homeassistant.const import STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import heating_image

FAULT = "sensor.fairland_heat_pump_fault"
INLET = "sensor.fairland_heat_pump_inlet_water_temperature"


@pytest.fixture
def platforms() -> list[Platform]:
    """Set up only the sensor platform."""
    return [Platform.SENSOR]


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_entities(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    init_integration: MockConfigEntry,
) -> None:
    """Test the sensors a heat pump gets, and their states."""
    await snapshot_platform(hass, entity_registry, snapshot, init_integration.entry_id)


async def test_enabled_by_default(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    init_integration: MockConfigEntry,
) -> None:
    """Test only the main readings and the fault start enabled."""
    entries = er.async_entries_for_config_entry(
        entity_registry, init_integration.entry_id
    )
    assert sorted(
        entry.entity_id.removeprefix("sensor.fairland_heat_pump_")
        for entry in entries
        if not entry.disabled
    ) == [
        "ambient_temperature",
        "compressor_current",
        "compressor_speed",
        "fault",
        "inlet_water_temperature",
        "outlet_water_temperature",
    ]


@pytest.mark.parametrize(
    ("register_image", "state"),
    [
        pytest.param(HEATING, "none", id="no_fault"),
        pytest.param(heating_image(discrete={51: True}), "e3", id="no_water_flow"),
        # Several codes at once: the first one the table lists.
        pytest.param(
            heating_image(discrete={51: True, 65: True}), "e3", id="two_codes"
        ),
        pytest.param(heating_image(discrete={91: True}), "fb", id="last_code"),
    ],
    indirect=["register_image"],
)
@pytest.mark.usefixtures("init_integration")
async def test_fault(hass: HomeAssistant, state: str) -> None:
    """Test the fault sensor shows the active code."""
    assert hass.states.get(FAULT).state == state


@pytest.mark.usefixtures("init_integration")
async def test_readings_fail_alone(
    hass: HomeAssistant, mock_unit: MockModbusUnit, freezer: FrozenDateTimeFactory
) -> None:
    """Test a failing readings block leaves the fault sensor available."""
    mock_unit.fail_read(3, IllegalDataAddressError(), register_type="input")
    freezer.tick(UPDATE_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(INLET).state == STATE_UNAVAILABLE
    assert hass.states.get(FAULT).state == "none"
