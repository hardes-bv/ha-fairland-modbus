"""Integrate Fairland pool heat pumps over Modbus into Home Assistant."""

from fairland_modbus.heat_pump import FairlandHeatPump

from homeassistant.components.modbus import async_get_unit
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_UNIT_ID
from .coordinator import FairlandConfigEntry, FairlandCoordinator
from .helpers import create_modbus_params

PLATFORMS: list[Platform] = [Platform.CLIMATE]


async def async_setup_entry(hass: HomeAssistant, entry: FairlandConfigEntry) -> bool:
    """Set up a Fairland heat pump from a config entry."""
    unit = async_get_unit(
        hass, entry, create_modbus_params(entry.data), entry.data[CONF_UNIT_ID]
    )
    coordinator = FairlandCoordinator(hass, entry, FairlandHeatPump(unit))
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FairlandConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
