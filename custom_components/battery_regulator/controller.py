"""Abstract battery controller interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BatteryController(ABC):
    """Abstract base class for battery controllers."""

    @abstractmethod
    async def set_power(self, power: int) -> None:
        """Set battery power. Negative=charge, positive=discharge, 0=idle."""
