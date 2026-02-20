"""Battery Regulator integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_MARSTEK_AUTO_MODE_BUTTON, CONF_MARSTEK_DEVICE_ID, DOMAIN
from .coordinator import BatteryRegulatorCoordinator
from .marstek_controller import MarstekController

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Battery Regulator from a config entry."""
    controller = MarstekController(
        hass,
        device_id=entry.data[CONF_MARSTEK_DEVICE_ID],
    )

    coordinator = BatteryRegulatorCoordinator(hass, dict(entry.data), controller)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: BatteryRegulatorCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        controller = coordinator.controller
        if isinstance(controller, MarstekController):
            auto_mode_button = entry.data.get(CONF_MARSTEK_AUTO_MODE_BUTTON)
            if auto_mode_button:
                try:
                    await controller.set_auto_mode(auto_mode_button)
                    _LOGGER.info("Battery regulator: restored auto mode on unload")
                except Exception:
                    _LOGGER.warning(
                        "Battery regulator: failed to restore auto mode on unload",
                        exc_info=True,
                    )
    return unload_ok
