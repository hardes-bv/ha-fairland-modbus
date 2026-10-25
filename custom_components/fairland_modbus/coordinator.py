"""Data update coordinator for the Fairland (Modbus) integration."""

import logging
from typing import override

from fairland_modbus import FairlandConnectionError, FairlandTimeoutError
from fairland_modbus.heat_pump import FairlandHeatPump
from modbus_connection.model import UpdateReport

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, MANUFACTURER, UPDATE_INTERVAL
from .helpers import error_detail

_LOGGER = logging.getLogger(__name__)

type FairlandConfigEntry = ConfigEntry[FairlandCoordinator]


class FairlandCoordinator(DataUpdateCoordinator[UpdateReport]):
    """Poll every block of the heat pump."""

    config_entry: FairlandConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: FairlandConfigEntry,
        heat_pump: FairlandHeatPump,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=UPDATE_INTERVAL,
        )
        self.heat_pump = heat_pump
        self._failing: set[str] = set()
        # The board reports no serial number.
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=MANUFACTURER,
            model="Inverter pool heat pump",
            name=entry.title,
        )

    @override
    async def _async_update_data(self) -> UpdateReport:
        try:
            report = await self.heat_pump.async_update()
        except FairlandTimeoutError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="no_response",
                translation_placeholders={"error": error_detail(err)},
            ) from err
        except FairlandConnectionError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": error_detail(err)},
            ) from err
        if not report.updated:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="no_block_answered",
            ) from ExceptionGroup(
                "every block failed to refresh", list(report.failed.values())
            )
        self._log_block_changes(report)
        return report

    def _log_block_changes(self, report: UpdateReport) -> None:
        """Log a block's first failure and its recovery, once each."""
        for name, cause in report.failed.items():
            if name not in self._failing:
                self._failing.add(name)
                _LOGGER.warning(
                    "%s: %s failed to refresh, its entities are unavailable: %s",
                    self.name,
                    name,
                    cause,
                )
        for name in report.updated & self._failing:
            self._failing.discard(name)
            _LOGGER.info("%s: %s is available again", self.name, name)
