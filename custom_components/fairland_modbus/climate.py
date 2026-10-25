"""Climate entity for the Fairland (Modbus) integration."""

from dataclasses import dataclass
from typing import Any, override

from fairland_modbus import FairlandRefusedError
from fairland_modbus.heat_pump import Function, WorkingMode

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ClimateEntity,
    ClimateEntityDescription,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import FairlandConfigEntry, FairlandCoordinator
from .entity import FairlandEntity, FairlandEntityDescription

PARALLEL_UPDATES = 1

# The board's automatic function heats or cools the water towards one
# setpoint, which is closest to Home Assistant's heat/cool mode.
FUNCTION_TO_HVAC_MODE = {
    Function.AUTO: HVACMode.HEAT_COOL,
    Function.HEATING: HVACMode.HEAT,
    Function.COOLING: HVACMode.COOL,
}
HVAC_MODE_TO_FUNCTION = {
    mode: function for function, mode in FUNCTION_TO_HVAC_MODE.items()
}

PRESET_MODES = {mode.name.lower(): mode for mode in WorkingMode}


@dataclass(frozen=True, kw_only=True)
class FairlandClimateEntityDescription(
    ClimateEntityDescription, FairlandEntityDescription
):
    """Describe the Fairland climate entity."""


HEAT_PUMP = FairlandClimateEntityDescription(
    key="heat_pump",
    translation_key="heat_pump",
    name=None,
    blocks=("controls", "settings"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FairlandConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Fairland climate entity."""
    async_add_entities([FairlandClimate(entry.runtime_data, HEAT_PUMP)])


class FairlandClimate(FairlandEntity, ClimateEntity):
    """The heat pump, as a water thermostat."""

    entity_description: FairlandClimateEntityDescription

    _attr_hvac_modes = [HVACMode.OFF, *FUNCTION_TO_HVAC_MODE.values()]
    _attr_preset_modes = list(PRESET_MODES)
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_target_temperature_step = 1
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        coordinator: FairlandCoordinator,
        entity_description: FairlandClimateEntityDescription,
    ) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator, entity_description)
        self._heat_pump = coordinator.heat_pump

    def _fresh(self, block: str) -> bool:
        """Whether a block outside this entity's own answered the last poll."""
        return block in self.coordinator.data.updated

    @property
    @override
    def current_temperature(self) -> float | None:
        """The water entering the heat pump: the pool temperature."""
        if not self._fresh("readings"):
            return None
        return self._heat_pump.readings.inlet_water_temperature

    @property
    @override
    def target_temperature(self) -> float | None:
        """The setpoint of the current function."""
        return self._heat_pump.target_temperature

    @property
    def _limits(self) -> tuple[int, int]:
        """The setpoint range of the current function."""
        function = self._heat_pump.function or Function.HEATING
        return self._heat_pump.target_temperature_limits(function)

    @property
    @override
    def min_temp(self) -> float:
        """The lowest setpoint the current function accepts."""
        return self._limits[0]

    @property
    @override
    def max_temp(self) -> float:
        """The highest setpoint the current function accepts."""
        return self._limits[1]

    @property
    @override
    def hvac_mode(self) -> HVACMode | None:
        """Off, or the function the heat pump is in."""
        power = self._heat_pump.power
        function = self._heat_pump.function
        if power is None or function is None:
            return None
        return FUNCTION_TO_HVAC_MODE[function] if power else HVACMode.OFF

    @property
    @override
    def hvac_action(self) -> HVACAction | None:
        """What the heat pump is doing right now."""
        heat_pump = self._heat_pump
        if heat_pump.power is False:
            return HVACAction.OFF
        if not self._fresh("status"):
            return None
        status = heat_pump.status
        if status.defrosting:
            return HVACAction.DEFROSTING
        if not status.compressor_demand:
            return HVACAction.IDLE
        if heat_pump.function is Function.COOLING:
            return HVACAction.COOLING
        if heat_pump.function is Function.HEATING:
            return HVACAction.HEATING
        # In the automatic function, the water tells which way it goes.
        if not self._fresh("readings"):
            return None
        readings = heat_pump.readings
        inlet = readings.inlet_water_temperature
        outlet = readings.outlet_water_temperature
        if inlet is not None and outlet is not None and outlet < inlet:
            return HVACAction.COOLING
        return HVACAction.HEATING

    @property
    @override
    def preset_mode(self) -> str | None:
        """The working mode."""
        mode = self._heat_pump.settings.working_mode
        return None if mode is None else mode.name.lower()

    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the setpoint, switching function first if asked to."""
        if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            await self.async_set_hvac_mode(hvac_mode)
        await self._async_write(
            self._heat_pump.async_set_target_temperature(kwargs[ATTR_TEMPERATURE])
        )

    @override
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Switch off, or switch on in a function."""
        if hvac_mode == HVACMode.OFF:
            await self._async_write(self._heat_pump.async_set_power(False))
            return
        function = HVAC_MODE_TO_FUNCTION[hvac_mode]
        if function is not self._heat_pump.function:
            await self._async_write(self._heat_pump.async_set_function(function))
        if not self._heat_pump.power:
            await self._async_write(self._heat_pump.async_set_power(True))

    @override
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Choose the working mode."""
        await self._async_write(self._async_set_working_mode(PRESET_MODES[preset_mode]))

    async def _async_set_working_mode(self, mode: WorkingMode) -> None:
        """Write the working mode, telling a mode the board kept apart."""
        try:
            await self._heat_pump.async_set_working_mode(mode)
        except FairlandRefusedError as err:
            # The read back already holds the mode the board kept.
            self.async_write_ha_state()
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="preset_refused"
            ) from err

    @override
    async def async_turn_on(self) -> None:
        """Switch the heat pump on in its current function."""
        await self._async_write(self._heat_pump.async_set_power(True))

    @override
    async def async_turn_off(self) -> None:
        """Switch the heat pump off."""
        await self._async_write(self._heat_pump.async_set_power(False))
