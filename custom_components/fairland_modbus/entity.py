"""Base entity for the Fairland (Modbus) integration."""

from collections.abc import Awaitable
from dataclasses import dataclass
from typing import override

from fairland_modbus import FairlandConnectionError, FairlandError, FairlandRefusedError

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FairlandCoordinator
from .helpers import error_detail


@dataclass(frozen=True, kw_only=True)
class FairlandEntityDescription(EntityDescription):
    """Which blocks of the heat pump an entity reads."""

    # Attribute names on FairlandHeatPump, like "readings".
    blocks: tuple[str, ...]


class FairlandEntity(CoordinatorEntity[FairlandCoordinator]):
    """An entity backed by one or more blocks of the heat pump.

    Blocks are read independently, so an entity is unavailable when one of
    its own blocks failed to read, not when any block did.
    """

    _attr_has_entity_name = True
    entity_description: FairlandEntityDescription

    def __init__(
        self,
        coordinator: FairlandCoordinator,
        entity_description: FairlandEntityDescription,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        # The board reports no serial number.
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{entity_description.key}"
        )
        self._attr_device_info = coordinator.device_info

    @property
    @override
    def available(self) -> bool:
        """Whether every block of this entity answered the most recent poll."""
        return super().available and all(
            block in self.coordinator.data.updated
            for block in self.entity_description.blocks
        )

    async def _async_write(self, write: Awaitable[None]) -> None:
        """Send a write to the heat pump, then refresh what it changed."""
        try:
            await write
        except FairlandRefusedError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_refused",
                translation_placeholders={"error": error_detail(err)},
            ) from err
        except FairlandConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"error": error_detail(err)},
            ) from err
        except FairlandError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_value",
                translation_placeholders={"error": error_detail(err)},
            ) from err
        await self.coordinator.async_request_refresh()
