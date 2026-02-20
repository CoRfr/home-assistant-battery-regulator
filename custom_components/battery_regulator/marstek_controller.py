"""Marstek battery controller implementation."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from .controller import BatteryController

_LOGGER = logging.getLogger(__name__)


class MarstekController(BatteryController):
    """Battery controller for Marstek batteries via marstek_local_api."""

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str,
    ) -> None:
        self._hass = hass
        self._device_id = device_id

    async def set_power(self, power: int) -> None:
        """Set battery power via passive mode. 0W = idle."""
        _LOGGER.debug("Marstek set_power: power=%dW", power)
        await self._hass.services.async_call(
            "marstek_local_api",
            "set_passive_mode",
            {
                "device_id": self._device_id,
                "power": power,
                "duration": 3600,
            },
        )

    async def set_auto_mode(self, auto_mode_button: str) -> None:
        """Press the auto mode button (used during integration unload only)."""
        _LOGGER.debug("Marstek set_auto_mode: pressing %s", auto_mode_button)
        await self._hass.services.async_call(
            "button",
            "press",
            {"entity_id": auto_mode_button},
        )
