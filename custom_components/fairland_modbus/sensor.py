"""Sensors for the Fairland (Modbus) integration."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from fairland_modbus.heat_pump import FAULT_CODES, FairlandHeatPump

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfFrequency,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FairlandConfigEntry
from .entity import FairlandEntity, FairlandEntityDescription

# Coordinator-based, so the platform sends nothing itself.
PARALLEL_UPDATES = 0

NO_FAULT = "none"
FAULT_OPTIONS = [NO_FAULT, *(code.lower() for code in FAULT_CODES.values())]


@dataclass(frozen=True, kw_only=True)
class FairlandSensorEntityDescription(
    SensorEntityDescription, FairlandEntityDescription
):
    """Describe a Fairland sensor."""

    value_fn: Callable[[FairlandHeatPump], float | str | None]


def _fault(heat_pump: FairlandHeatPump) -> str:
    """The first active code, or none."""
    codes = heat_pump.status.active_codes
    return codes[0].lower() if codes else NO_FAULT


def _temperature(
    key: str, value_fn: Callable[[FairlandHeatPump], float | None], *, main: bool
) -> FairlandSensorEntityDescription:
    """A temperature reading; the refrigerant ones are diagnostics."""
    return FairlandSensorEntityDescription(
        key=key,
        translation_key=key,
        blocks=("readings",),
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=None if main else EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=main,
        value_fn=value_fn,
    )


SENSORS: tuple[FairlandSensorEntityDescription, ...] = (
    _temperature(
        "inlet_water_temperature",
        lambda hp: hp.readings.inlet_water_temperature,
        main=True,
    ),
    _temperature(
        "outlet_water_temperature",
        lambda hp: hp.readings.outlet_water_temperature,
        main=True,
    ),
    _temperature(
        "ambient_temperature",
        lambda hp: hp.readings.ambient_temperature,
        main=True,
    ),
    _temperature(
        "exhaust_gas_temperature",
        lambda hp: hp.readings.exhaust_gas_temperature,
        main=False,
    ),
    _temperature(
        "evaporator_coil_temperature",
        lambda hp: hp.readings.evaporator_coil_temperature,
        main=False,
    ),
    _temperature(
        "suction_gas_temperature",
        lambda hp: hp.readings.suction_gas_temperature,
        main=False,
    ),
    _temperature(
        "heat_exchanger_coil_temperature",
        lambda hp: hp.readings.heat_exchanger_coil_temperature,
        main=False,
    ),
    _temperature(
        "cooling_plate_temperature",
        lambda hp: hp.readings.cooling_plate_temperature,
        main=False,
    ),
    FairlandSensorEntityDescription(
        key="compressor_speed",
        translation_key="compressor_speed",
        blocks=("readings",),
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda hp: hp.readings.compressor_speed,
    ),
    FairlandSensorEntityDescription(
        key="compressor_current",
        translation_key="compressor_current",
        blocks=("readings",),
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=1,
        value_fn=lambda hp: hp.readings.compressor_current,
    ),
    FairlandSensorEntityDescription(
        key="compressor_frequency",
        translation_key="compressor_frequency",
        blocks=("readings",),
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda hp: hp.readings.compressor_frequency,
    ),
    FairlandSensorEntityDescription(
        key="compressor_target_frequency",
        translation_key="compressor_target_frequency",
        blocks=("readings",),
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda hp: hp.readings.compressor_target_frequency,
    ),
    FairlandSensorEntityDescription(
        key="pfc_voltage",
        translation_key="pfc_voltage",
        blocks=("readings",),
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda hp: hp.readings.pfc_voltage,
    ),
    FairlandSensorEntityDescription(
        key="expansion_valve_opening",
        translation_key="expansion_valve_opening",
        blocks=("readings",),
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda hp: hp.readings.expansion_valve_opening,
    ),
    FairlandSensorEntityDescription(
        key="fan_speed",
        translation_key="fan_speed",
        blocks=("readings",),
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda hp: hp.readings.fan_speed,
    ),
    FairlandSensorEntityDescription(
        key="fault",
        translation_key="fault",
        blocks=("status",),
        device_class=SensorDeviceClass.ENUM,
        options=FAULT_OPTIONS,
        value_fn=_fault,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FairlandConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Fairland sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        FairlandSensor(coordinator, description) for description in SENSORS
    )


class FairlandSensor(FairlandEntity, SensorEntity):
    """A Fairland sensor."""

    entity_description: FairlandSensorEntityDescription

    @property
    @override
    def native_value(self) -> float | str | None:
        """The value the heat pump reports."""
        return self.entity_description.value_fn(self.coordinator.heat_pump)
