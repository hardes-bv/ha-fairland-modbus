"""Helpers for the Fairland (Modbus) integration."""

from collections.abc import Mapping
from typing import Any

from modbus_connection import ModbusSerialParams, ModbusTcpParams

from homeassistant.const import CONF_DEVICE, CONF_HOST, CONF_PORT, CONF_TYPE

from .const import SERIAL_BAUDRATE, SERIAL_PARITY, SERIAL_STOPBITS, TYPE_SERIAL


def create_modbus_params(
    data: Mapping[str, Any],
) -> ModbusSerialParams | ModbusTcpParams:
    """Build the Modbus link parameters from config entry data.

    The board's line settings are fixed (9600 baud, 8N1), so a serial link
    only needs the port.
    """
    if data[CONF_TYPE] == TYPE_SERIAL:
        return ModbusSerialParams(
            device=data[CONF_DEVICE],
            baudrate=SERIAL_BAUDRATE,
            parity=SERIAL_PARITY,
            stopbits=SERIAL_STOPBITS,
        )
    return ModbusTcpParams(host=data[CONF_HOST], port=data[CONF_PORT])


def error_detail(err: Exception) -> str:
    """The transport or device error behind a library exception.

    The library's own message repeats what the translated message says.
    """
    return str(err.__cause__ or err)
