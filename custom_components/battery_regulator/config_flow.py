"""Config flow for Battery Regulator."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.helpers import selector

from .const import (
    CONF_BASE_LOAD_W,
    CONF_BATTERY_CAPACITY_WH,
    CONF_BATTERY_POWER_SENSOR,
    CONF_BATTERY_POWER_UNSIGNED,
    CONF_BATTERY_SOC_SENSOR,
    CONF_DISCHARGE_MIN_POWER,
    CONF_GRID_POWER_SENSOR,
    CONF_HC_CHARGE_RATE,
    CONF_HC_HP_SENSOR,
    CONF_MARSTEK_AUTO_MODE_BUTTON,
    CONF_MARSTEK_DEVICE_ID,
    CONF_MAX_CHARGE_RATE,
    CONF_MAX_DISCHARGE_RATE,
    CONF_SELF_CONSUMPTION,
    CONF_SOLAR_FORECAST_SENSOR,
    CONF_SOLAR_PRODUCTION_SENSOR,
    CONF_SOLAR_REMAINING_SENSOR,
    CONF_SURPLUS_SOC_MAX,
    CONF_SURPLUS_THRESHOLD,
    CONF_TEMPO_COLOR_SENSOR,
    CONF_UPDATE_INTERVAL,
    DEFAULT_BASE_LOAD_W,
    DEFAULT_BATTERY_CAPACITY_WH,
    DEFAULT_DISCHARGE_MIN_POWER,
    DEFAULT_HC_CHARGE_RATE,
    DEFAULT_MAX_CHARGE_RATE,
    DEFAULT_MAX_DISCHARGE_RATE,
    DEFAULT_SURPLUS_SOC_MAX,
    DEFAULT_SURPLUS_THRESHOLD,
    DEFAULT_UPDATE_INTERVAL_SECONDS,
    DOMAIN,
)

STEP_GENERIC_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_GRID_POWER_SENSOR): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor"),
        ),
        vol.Required(CONF_SOLAR_PRODUCTION_SENSOR): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor"),
        ),
        vol.Required(CONF_BATTERY_SOC_SENSOR): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor"),
        ),
        vol.Required(CONF_BATTERY_POWER_SENSOR): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor"),
        ),
        vol.Optional(CONF_BATTERY_POWER_UNSIGNED, default=False): selector.BooleanSelector(),
        vol.Required(CONF_HC_HP_SENSOR): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="binary_sensor"),
        ),
        vol.Required(CONF_SOLAR_FORECAST_SENSOR): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor"),
        ),
        vol.Required(CONF_SOLAR_REMAINING_SENSOR): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor"),
        ),
        vol.Optional(CONF_TEMPO_COLOR_SENSOR): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor"),
        ),
        vol.Optional(
            CONF_BATTERY_CAPACITY_WH, default=DEFAULT_BATTERY_CAPACITY_WH
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1000,
                max=50000,
                step=100,
                unit_of_measurement="Wh",
                mode=selector.NumberSelectorMode.BOX,
            ),
        ),
        vol.Optional(CONF_BASE_LOAD_W, default=DEFAULT_BASE_LOAD_W): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=5000,
                step=50,
                unit_of_measurement="W",
                mode=selector.NumberSelectorMode.BOX,
            ),
        ),
        vol.Optional(CONF_HC_CHARGE_RATE, default=DEFAULT_HC_CHARGE_RATE): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=100,
                max=5000,
                step=100,
                unit_of_measurement="W",
                mode=selector.NumberSelectorMode.BOX,
            ),
        ),
        vol.Optional(
            CONF_MAX_CHARGE_RATE, default=DEFAULT_MAX_CHARGE_RATE
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=100,
                max=5000,
                step=100,
                unit_of_measurement="W",
                mode=selector.NumberSelectorMode.BOX,
            ),
        ),
        vol.Optional(
            CONF_MAX_DISCHARGE_RATE, default=DEFAULT_MAX_DISCHARGE_RATE
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=100,
                max=5000,
                step=100,
                unit_of_measurement="W",
                mode=selector.NumberSelectorMode.BOX,
            ),
        ),
        vol.Optional(
            CONF_SURPLUS_THRESHOLD, default=DEFAULT_SURPLUS_THRESHOLD
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=10,
                max=1000,
                step=10,
                unit_of_measurement="W",
                mode=selector.NumberSelectorMode.BOX,
            ),
        ),
        vol.Optional(
            CONF_SURPLUS_SOC_MAX, default=DEFAULT_SURPLUS_SOC_MAX
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=50,
                max=100,
                step=1,
                unit_of_measurement="%",
                mode=selector.NumberSelectorMode.BOX,
            ),
        ),
        vol.Optional(
            CONF_DISCHARGE_MIN_POWER, default=DEFAULT_DISCHARGE_MIN_POWER
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=500,
                step=10,
                unit_of_measurement="W",
                mode=selector.NumberSelectorMode.BOX,
            ),
        ),
        vol.Optional(
            CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL_SECONDS
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=5,
                max=300,
                step=5,
                unit_of_measurement="s",
                mode=selector.NumberSelectorMode.BOX,
            ),
        ),
        vol.Optional(CONF_SELF_CONSUMPTION, default=True): selector.BooleanSelector(),
    }
)

STEP_MARSTEK_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MARSTEK_DEVICE_ID): str,
        vol.Required(CONF_MARSTEK_AUTO_MODE_BUTTON): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="button"),
        ),
    }
)


def _schema_with_defaults(schema: vol.Schema, defaults: dict[str, Any]) -> vol.Schema:
    """Return a copy of the schema with defaults filled from existing config."""
    new_schema = {}
    for key, val in schema.schema.items():
        if key in defaults:
            new_key = (
                vol.Optional(str(key), default=defaults[key])
                if isinstance(key, vol.Optional)
                else vol.Required(str(key), default=defaults[key])
            )
            new_schema[new_key] = val
        else:
            new_schema[key] = val
    return vol.Schema(new_schema)


class BatteryRegulatorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Battery Regulator."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return BatteryRegulatorOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> dict:
        """Step 1: Generic battery sensors."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_marstek()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_GENERIC_SCHEMA,
        )

    async def async_step_marstek(self, user_input: dict[str, Any] | None = None) -> dict:
        """Step 2: Marstek-specific configuration."""
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(
                title="Battery Regulator",
                data=self._data,
            )

        return self.async_show_form(
            step_id="marstek",
            data_schema=STEP_MARSTEK_SCHEMA,
        )


class BatteryRegulatorOptionsFlow(OptionsFlow):
    """Handle options for Battery Regulator."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry
        self._data: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> dict:
        """Step 1: Generic battery sensors (pre-filled with current values)."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_marstek()

        schema = _schema_with_defaults(STEP_GENERIC_SCHEMA, self._config_entry.data)
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_marstek(self, user_input: dict[str, Any] | None = None) -> dict:
        """Step 2: Marstek-specific configuration."""
        if user_input is not None:
            self._data.update(user_input)
            # Update entry.data and trigger reload
            self.hass.config_entries.async_update_entry(self._config_entry, data=self._data)
            await self.hass.config_entries.async_reload(self._config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        schema = _schema_with_defaults(STEP_MARSTEK_SCHEMA, self._config_entry.data)
        return self.async_show_form(step_id="marstek", data_schema=schema)
