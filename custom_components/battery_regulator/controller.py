"""Abstract battery controller interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BatteryController(ABC):
    """Abstract base class for battery controllers."""

    @abstractmethod
    async def set_passive_mode(self, power: int, duration: int) -> None:
        """Set passive mode with given power and duration.

        Args:
            power: Power in watts. Negative=charge, positive=discharge.
            duration: Duration in seconds.
        """

    @abstractmethod
    async def set_auto_mode(self) -> None:
        """Switch battery back to auto mode."""
