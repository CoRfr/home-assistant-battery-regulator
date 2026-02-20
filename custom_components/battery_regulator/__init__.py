"""Battery Regulator integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_MARSTEK_AUTO_MODE_BUTTON, CONF_MARSTEK_DEVICE_ID, DOMAIN
from .coordinator import BatteryRegulatorCoordinator
from .marstek_controller import MarstekController

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Battery Regulator from a config entry."""
    controller = MarstekController(
        hass,
        device_id=entry.data[CONF_MARSTEK_DEVICE_ID],
        auto_mode_button=entry.data[CONF_MARSTEK_AUTO_MODE_BUTTON],
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
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
