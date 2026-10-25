"""Tests for the Fairland (Modbus) config flow."""

from typing import Any
from unittest.mock import AsyncMock, PropertyMock, patch

from modbus_connection import (
    GatewayTargetError,
    IllegalFunctionError,
    ModbusConnectionError,
    ModbusTimeoutError,
)
from modbus_connection.mock import MockModbusConnection, MockModbusUnit
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fairland_modbus.const import DOMAIN
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError

from . import (
    MOCK_SERIAL_DATA,
    MOCK_SERIAL_INPUT,
    MOCK_TCP_DATA,
    MOCK_TCP_INPUT,
    MOCK_TITLE,
)

pytestmark = pytest.mark.usefixtures("mock_temporary_unit")


async def _start(hass: HomeAssistant, step: str) -> str:
    """Open the user flow and pick a connection type."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": step}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == step
    return result["flow_id"]


@pytest.mark.parametrize(
    ("step", "user_input", "data"),
    [
        pytest.param("tcp", MOCK_TCP_INPUT, MOCK_TCP_DATA, id="tcp"),
        pytest.param("serial", MOCK_SERIAL_INPUT, MOCK_SERIAL_DATA, id="serial"),
    ],
)
async def test_user_flow(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    step: str,
    user_input: dict[str, Any],
    data: dict[str, Any],
) -> None:
    """Test adding a heat pump over each kind of link."""
    flow_id = await _start(hass, step)
    result = await hass.config_entries.flow.async_configure(flow_id, user_input)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == MOCK_TITLE
    assert result["data"] == data
    assert result["result"].unique_id is None
    assert len(mock_setup_entry.mock_calls) == 1


@pytest.mark.parametrize(
    ("space", "address", "value", "error"),
    [
        pytest.param("input", 3, 0, "not_a_fairland_heat_pump", id="cold_water"),
        pytest.param("holding", 3, 200, "not_a_fairland_heat_pump", id="setpoint"),
    ],
)
async def test_user_flow_other_device(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_unit: MockModbusUnit,
    space: str,
    address: int,
    value: int,
    error: str,
) -> None:
    """Test a device that answers unlike the board, then the right one."""
    store = getattr(mock_unit, space)
    original = store[address]
    store[address] = value
    flow_id = await _start(hass, "tcp")

    result = await hass.config_entries.flow.async_configure(flow_id, MOCK_TCP_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    store[address] = original
    result = await hass.config_entries.flow.async_configure(flow_id, MOCK_TCP_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_board_of_another_family(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_unit: MockModbusUnit,
) -> None:
    """Test a board that refuses every read of the table, like a PC1004."""
    mock_unit.fail_requests(IllegalFunctionError())
    flow_id = await _start(hass, "tcp")

    result = await hass.config_entries.flow.async_configure(flow_id, MOCK_TCP_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "not_a_fairland_heat_pump"}

    mock_unit.fail_requests(None)
    result = await hass.config_entries.flow.async_configure(flow_id, MOCK_TCP_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_unreachable(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_unit: MockModbusUnit,
) -> None:
    """Test an unreachable gateway shows an error, and the user can retry."""
    mock_unit.fail_requests(ModbusConnectionError())
    flow_id = await _start(hass, "tcp")

    result = await hass.config_entries.flow.async_configure(flow_id, MOCK_TCP_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    mock_unit.fail_requests(None)
    result = await hass.config_entries.flow.async_configure(flow_id, MOCK_TCP_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(ModbusTimeoutError(), id="timeout"),
        pytest.param(GatewayTargetError(), id="gateway_target_failed"),
    ],
)
async def test_user_flow_unit_silent(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_connection: MockModbusConnection,
    mock_unit: MockModbusUnit,
    error: Exception,
) -> None:
    """Test a gateway that answers while the heat pump behind it does not."""
    await mock_connection.connect()
    mock_unit.fail_requests(error)
    flow_id = await _start(hass, "tcp")

    result = await hass.config_entries.flow.async_configure(flow_id, MOCK_TCP_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unit_silent"}

    mock_unit.fail_requests(None)
    result = await hass.config_entries.flow.async_configure(flow_id, MOCK_TCP_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_timeout_without_a_link(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_unit: MockModbusUnit,
) -> None:
    """Test a timeout before any link is up reads as unreachable."""
    mock_unit.fail_requests(ModbusTimeoutError())
    flow_id = await _start(hass, "tcp")
    with patch.object(
        MockModbusUnit, "connected", new_callable=PropertyMock, return_value=False
    ):
        result = await hass.config_entries.flow.async_configure(flow_id, MOCK_TCP_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    mock_unit.fail_requests(None)
    result = await hass.config_entries.flow.async_configure(flow_id, MOCK_TCP_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        pytest.param(HomeAssistantError, "link_in_use", id="link_in_use"),
        pytest.param(RuntimeError, "unknown", id="unexpected"),
    ],
)
async def test_user_flow_probe_raises(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    side_effect: type[Exception],
    error: str,
) -> None:
    """Test errors raised around the probe itself."""
    flow_id = await _start(hass, "tcp")
    with patch(
        "custom_components.fairland_modbus.config_flow.FairlandHeatPump.async_validate",
        side_effect=side_effect,
    ):
        result = await hass.config_entries.flow.async_configure(flow_id, MOCK_TCP_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    result = await hass.config_entries.flow.async_configure(flow_id, MOCK_TCP_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("step", "entry_data", "user_input"),
    [
        pytest.param("tcp", MOCK_TCP_DATA, MOCK_TCP_INPUT, id="tcp"),
        pytest.param("serial", MOCK_SERIAL_DATA, MOCK_SERIAL_INPUT, id="serial"),
    ],
    indirect=["entry_data"],
)
async def test_user_flow_already_configured(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    step: str,
    user_input: dict[str, Any],
) -> None:
    """Test the same heat pump on the same link cannot be added twice."""
    mock_config_entry.add_to_hass(hass)
    flow_id = await _start(hass, step)
    result = await hass.config_entries.flow.async_configure(flow_id, user_input)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_another_heat_pump_on_the_same_gateway(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_config_entry: MockConfigEntry,
    mock_connection: MockModbusConnection,
) -> None:
    """Test a second heat pump at another address on one gateway."""
    mock_config_entry.add_to_hass(hass)
    first, second = mock_connection.for_unit(1), mock_connection.for_unit(2)
    second.input.update(first.input)
    second.holding.update(first.holding)
    flow_id = await _start(hass, "tcp")
    result = await hass.config_entries.flow.async_configure(
        flow_id, {**MOCK_TCP_INPUT, "unit_id": 2}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
