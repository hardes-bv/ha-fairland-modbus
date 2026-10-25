"""Tests for the Fairland (Modbus) climate entity."""

from copy import deepcopy
from datetime import timedelta
from typing import Any

from fairland_modbus.heat_pump.testing import HEATING
from freezegun.api import FrozenDateTimeFactory
from modbus_connection import (
    IllegalDataAddressError,
    IllegalDataValueError,
    ModbusConnectionError,
)
from modbus_connection.mock import MockModbusUnit, WriteEvent
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

from custom_components.fairland_modbus.const import UPDATE_INTERVAL
from homeassistant.components.climate import (
    ATTR_HVAC_ACTION,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

CLIMATE = "climate.fairland_heat_pump"
COIL = 0x05
FC06 = 0x06


def _image(**changes: dict[int, Any]) -> dict[str, dict[int, Any]]:
    """The heating image with some registers changed."""
    image = deepcopy(HEATING)
    for space, values in changes.items():
        image[space].update(values)
    return image


@pytest.fixture
def writes(mock_unit: MockModbusUnit) -> list[WriteEvent]:
    """The writes the mock heat pump receives."""
    events: list[WriteEvent] = []
    mock_unit.on_write(events.append)
    return events


@pytest.mark.parametrize(
    ("register_image", "domain", "service", "entity_id", "data", "expected"),
    [
        pytest.param(
            HEATING,
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            CLIMATE,
            {ATTR_HVAC_MODE: HVACMode.OFF},
            [WriteEvent("coil", 0, [False], COIL)],
            id="hvac_off",
        ),
        pytest.param(
            HEATING,
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            CLIMATE,
            {ATTR_HVAC_MODE: HVACMode.COOL},
            [WriteEvent("holding", 0, [2], FC06)],
            id="hvac_cool_while_on",
        ),
        pytest.param(
            _image(coil={0: False}),
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            CLIMATE,
            {ATTR_HVAC_MODE: HVACMode.HEAT},
            [WriteEvent("coil", 0, [True], COIL)],
            id="hvac_heat_while_off",
        ),
        pytest.param(
            _image(coil={0: False}),
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            CLIMATE,
            {ATTR_HVAC_MODE: HVACMode.HEAT_COOL},
            [
                WriteEvent("holding", 0, [0], FC06),
                WriteEvent("coil", 0, [True], COIL),
            ],
            id="hvac_auto_while_off",
        ),
        pytest.param(
            HEATING,
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            CLIMATE,
            {ATTR_TEMPERATURE: 30},
            [WriteEvent("holding", 3, [120], FC06)],
            id="heating_setpoint",
        ),
        pytest.param(
            HEATING,
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            CLIMATE,
            {ATTR_TEMPERATURE: 25, ATTR_HVAC_MODE: HVACMode.COOL},
            [
                WriteEvent("holding", 0, [2], FC06),
                WriteEvent("holding", 4, [110], FC06),
            ],
            id="cooling_setpoint_with_mode",
        ),
        pytest.param(
            HEATING,
            CLIMATE_DOMAIN,
            SERVICE_SET_PRESET_MODE,
            CLIMATE,
            {ATTR_PRESET_MODE: "super_silence"},
            [WriteEvent("holding", 1, [2], FC06)],
            id="super_silence",
        ),
        pytest.param(
            _image(coil={0: False}),
            CLIMATE_DOMAIN,
            SERVICE_TURN_ON,
            CLIMATE,
            {},
            [WriteEvent("coil", 0, [True], COIL)],
            id="turn_on",
        ),
        pytest.param(
            HEATING,
            CLIMATE_DOMAIN,
            SERVICE_TURN_OFF,
            CLIMATE,
            {},
            [WriteEvent("coil", 0, [False], COIL)],
            id="turn_off",
        ),
    ],
    indirect=["register_image"],
)
@pytest.mark.usefixtures("init_integration")
async def test_command(
    hass: HomeAssistant,
    writes: list[WriteEvent],
    domain: str,
    service: str,
    entity_id: str,
    data: dict[str, Any],
    expected: list[WriteEvent],
) -> None:
    """Test each command sends exactly the expected Modbus writes."""
    await hass.services.async_call(
        domain, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
    )
    assert writes == expected


@pytest.mark.usefixtures("init_integration")
async def test_switch_on_right_after_a_switch_off(
    hass: HomeAssistant, writes: list[WriteEvent]
) -> None:
    """Test a switch-on still goes out while the coordinator debounces."""
    for service, data in (
        (SERVICE_SET_PRESET_MODE, {ATTR_PRESET_MODE: "silence"}),
        (SERVICE_TURN_OFF, {}),
        (SERVICE_SET_HVAC_MODE, {ATTR_HVAC_MODE: HVACMode.HEAT}),
    ):
        await hass.services.async_call(
            CLIMATE_DOMAIN, service, {ATTR_ENTITY_ID: CLIMATE, **data}, blocking=True
        )
    assert writes == [
        WriteEvent("holding", 1, [1], FC06),
        WriteEvent("coil", 0, [False], COIL),
        WriteEvent("coil", 0, [True], COIL),
    ]


@pytest.mark.parametrize(
    ("error", "translation_key"),
    [
        pytest.param(IllegalDataValueError(), "preset_refused", id="refused"),
        pytest.param(ModbusConnectionError(), "write_failed", id="unreachable"),
    ],
)
@pytest.mark.usefixtures("init_integration")
async def test_failed_preset(
    hass: HomeAssistant,
    mock_unit: MockModbusUnit,
    error: Exception,
    translation_key: str,
) -> None:
    """Test a working mode the board refuses raises a translated error."""
    mock_unit.fail_write(1, error)
    with pytest.raises(HomeAssistantError) as exc_info:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_PRESET_MODE,
            {ATTR_ENTITY_ID: CLIMATE, ATTR_PRESET_MODE: "turbo"},
            blocking=True,
        )
    assert exc_info.value.translation_key == translation_key


async def test_preset_the_board_keeps(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_unit: MockModbusUnit
) -> None:
    """Test a working mode acknowledged but not applied raises and shows the kept one."""
    kept = mock_unit.holding[1]

    def keep(event: WriteEvent) -> None:
        if event.register_type == "holding" and event.address == 1:
            mock_unit.holding[1] = kept

    mock_unit.on_write(keep)

    with pytest.raises(HomeAssistantError) as exc_info:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_PRESET_MODE,
            {ATTR_ENTITY_ID: CLIMATE, ATTR_PRESET_MODE: "turbo"},
            blocking=True,
        )

    assert exc_info.value.translation_key == "preset_refused"
    assert hass.states.get(CLIMATE).attributes[ATTR_PRESET_MODE] == "smart"


@pytest.mark.usefixtures("init_integration")
async def test_climate_follows_the_heat_pump(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Test the climate entity after a command and the refreshes it triggers."""
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: CLIMATE, ATTR_TEMPERATURE: 25, ATTR_HVAC_MODE: HVACMode.COOL},
        blocking=True,
    )
    # The second write's refresh waits out the coordinator's debounce.
    freezer.tick(timedelta(seconds=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    state = hass.states.get(CLIMATE)
    assert state.state == HVACMode.COOL
    assert state.attributes[ATTR_TEMPERATURE] == 25
    assert (state.attributes["min_temp"], state.attributes["max_temp"]) == (12, 30)


@pytest.mark.parametrize(
    ("register_image", "action"),
    [
        pytest.param(HEATING, HVACAction.HEATING, id="heating"),
        pytest.param(_image(coil={0: False}), HVACAction.OFF, id="off"),
        pytest.param(_image(discrete={1: True}), HVACAction.DEFROSTING, id="defrost"),
        pytest.param(_image(discrete={17: False}), HVACAction.IDLE, id="idle"),
        pytest.param(_image(holding={0: 2}), HVACAction.COOLING, id="cooling"),
        pytest.param(_image(holding={0: 0}), HVACAction.HEATING, id="auto_heating"),
        pytest.param(
            _image(holding={0: 0}, input={4: 108}),
            HVACAction.COOLING,
            id="auto_cooling",
        ),
    ],
    indirect=["register_image"],
)
@pytest.mark.usefixtures("init_integration")
async def test_hvac_action(hass: HomeAssistant, action: HVACAction) -> None:
    """Test what the climate entity says the heat pump is doing."""
    assert hass.states.get(CLIMATE).attributes[ATTR_HVAC_ACTION] == action


@pytest.mark.usefixtures("init_integration")
async def test_hvac_action_without_status(
    hass: HomeAssistant, mock_unit: MockModbusUnit, freezer: FrozenDateTimeFactory
) -> None:
    """Test the action is unknown while the status block fails."""
    mock_unit.fail_read(0, IllegalDataAddressError(), register_type="discrete")
    freezer.tick(UPDATE_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(CLIMATE).attributes.get(ATTR_HVAC_ACTION) is None


@pytest.mark.parametrize("register_image", [_image(holding={0: 0})], indirect=True)
@pytest.mark.usefixtures("init_integration")
async def test_auto_action_without_water_temperatures(
    hass: HomeAssistant, mock_unit: MockModbusUnit, freezer: FrozenDateTimeFactory
) -> None:
    """Test the automatic direction is unknown without the readings."""
    mock_unit.fail_read(3, IllegalDataAddressError(), register_type="input")
    freezer.tick(UPDATE_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    state = hass.states.get(CLIMATE)
    assert state.attributes.get(ATTR_HVAC_ACTION) is None
    assert state.attributes.get("current_temperature") is None


@pytest.mark.parametrize(
    "register_image", [_image(holding={0: 9, 1: 7})], indirect=True
)
@pytest.mark.usefixtures("init_integration")
async def test_unknown_function_and_mode(hass: HomeAssistant) -> None:
    """Test codes the table does not list leave mode and preset unknown."""
    state = hass.states.get(CLIMATE)
    assert state.state == STATE_UNKNOWN
    assert state.attributes[ATTR_PRESET_MODE] is None
    assert state.attributes[ATTR_TEMPERATURE] is None
    assert (state.attributes["min_temp"], state.attributes["max_temp"]) == (18, 40)


async def test_entity(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    init_integration: MockConfigEntry,
) -> None:
    """Test the climate entity a heat pump gets, and its state."""
    await snapshot_platform(hass, entity_registry, snapshot, init_integration.entry_id)


@pytest.mark.usefixtures("init_integration")
async def test_setpoint_the_board_refuses(
    hass: HomeAssistant, mock_unit: MockModbusUnit
) -> None:
    """Test a setpoint write the board answers with an exception."""
    mock_unit.fail_write(3, IllegalDataValueError())
    with pytest.raises(HomeAssistantError) as exc_info:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: CLIMATE, ATTR_TEMPERATURE: 30},
            blocking=True,
        )
    assert exc_info.value.translation_key == "write_refused"


@pytest.mark.usefixtures("init_integration")
async def test_setpoint_the_library_refuses(
    hass: HomeAssistant, writes: list[WriteEvent]
) -> None:
    """Test a setpoint between two whole degrees is refused before any write."""
    with pytest.raises(ServiceValidationError) as exc_info:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: CLIMATE, ATTR_TEMPERATURE: 28.5},
            blocking=True,
        )
    assert exc_info.value.translation_key == "invalid_value"
    assert writes == []
