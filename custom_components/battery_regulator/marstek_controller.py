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
        auto_mode_button: str,
    ) -> None:
        self._hass = hass
        self._device_id = device_id
        self._auto_mode_button = auto_mode_button

    async def set_passive_mode(self, power: int, duration: int) -> None:
        """Set passive mode via marstek_local_api service."""
        _LOGGER.debug(
            "Marstek set_passive_mode: power=%dW, duration=%ds",
            power,
            duration,
        )
        await self._hass.services.async_call(
            "marstek_local_api",
            "set_passive_mode",
            {
                "device_id": self._device_id,
                "power": power,
                "duration": duration,
            },
        )

    async def set_auto_mode(self) -> None:
        """Press the auto mode button."""
        _LOGGER.debug("Marstek set_auto_mode: pressing %s", self._auto_mode_button)
        await self._hass.services.async_call(
            "button",
            "press",
            {"entity_id": self._auto_mode_button},
        )
