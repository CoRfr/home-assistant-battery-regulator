"""Sensor entities for Battery Regulator."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BatteryRegulatorCoordinator

ENTITY_ID_PREFIX = "sensor.battery_regulator_"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities from a config entry."""
    coordinator: BatteryRegulatorCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            BatteryRegulatorTargetSOC(coordinator, entry),
            BatteryRegulatorReserveSOC(coordinator, entry),
            BatteryRegulatorMode(coordinator, entry),
            BatteryRegulatorCommandedPower(coordinator, entry),
            BatteryRegulatorBatteryPower(coordinator, entry),
        ]
    )


class BatteryRegulatorBaseSensor(CoordinatorEntity[BatteryRegulatorCoordinator], SensorEntity):
    """Base class for battery regulator sensors."""

    def __init__(
        self,
        coordinator: BatteryRegulatorCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = f"Battery Regulator {name}"
        self.entity_id = f"{ENTITY_ID_PREFIX}{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Battery Regulator",
            manufacturer="Custom",
            model="Battery Regulator",
            sw_version="1.0.0",
            entry_type=None,
        )


class BatteryRegulatorTargetSOC(BatteryRegulatorBaseSensor):
    """Target SOC sensor."""

    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:battery-charging-medium"

    def __init__(self, coordinator: BatteryRegulatorCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "target_soc", "Target SOC")

    @property
    def native_value(self) -> int:
        return self.coordinator.target_soc


class BatteryRegulatorReserveSOC(BatteryRegulatorBaseSensor):
    """Reserve SOC sensor."""

    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:battery-lock"

    def __init__(self, coordinator: BatteryRegulatorCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "reserve_soc", "Reserve SOC")

    @property
    def native_value(self) -> int:
        return self.coordinator.reserve_soc


class BatteryRegulatorMode(BatteryRegulatorBaseSensor):
    """Current regulation mode sensor."""

    _attr_icon = "mdi:battery-sync"

    def __init__(self, coordinator: BatteryRegulatorCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "mode", "Mode")

    @property
    def native_value(self) -> str:
        return self.coordinator.current_mode.value


class BatteryRegulatorCommandedPower(BatteryRegulatorBaseSensor):
    """Commanded power sensor."""

    _attr_native_unit_of_measurement = "W"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: BatteryRegulatorCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "commanded_power", "Commanded Power")

    @property
    def native_value(self) -> int:
        return self.coordinator.last_commanded_power


class BatteryRegulatorBatteryPower(BatteryRegulatorBaseSensor):
    """Battery power with sign (based on current mode)."""

    _attr_native_unit_of_measurement = "W"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: BatteryRegulatorCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "battery_power", "Battery Power")

    @property
    def native_value(self) -> int:
        return self.coordinator.battery_power_signed
