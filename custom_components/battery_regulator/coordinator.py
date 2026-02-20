"""DataUpdateCoordinator for Battery Regulator."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BASE_LOAD_W,
    CONF_BATTERY_CAPACITY_WH,
    CONF_BATTERY_POWER_SENSOR,
    CONF_BATTERY_SOC_SENSOR,
    CONF_DISCHARGE_MIN_POWER,
    CONF_GRID_POWER_SENSOR,
    CONF_HC_CHARGE_RATE,
    CONF_HC_HP_SENSOR,
    CONF_MAX_CHARGE_RATE,
    CONF_MAX_DISCHARGE_RATE,
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
    MIN_MODE_CHANGE_SECONDS,
    RETRY_DELAY_SECONDS,
    RETRY_MAX_ATTEMPTS,
)
from .controller import BatteryController
from .regulator import (
    Config,
    Decision,
    Mode,
    State,
    compute_reserve_soc,
    compute_target_soc,
    regulate,
)

_LOGGER = logging.getLogger(__name__)


class BatteryRegulatorCoordinator(DataUpdateCoordinator[Decision]):
    """Coordinator that reads sensors, runs regulation logic, and acts."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict,
        controller: BatteryController,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=config.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_SECONDS)
            ),
        )
        self._config = config
        self._controller = controller
        self._current_mode = Mode.AUTO
        self._last_commanded_power = 0
        self._last_mode_change_time: datetime = dt_util.utcnow()
        self._reg_config = Config(
            battery_capacity_wh=config.get(CONF_BATTERY_CAPACITY_WH, DEFAULT_BATTERY_CAPACITY_WH),
            base_load_w=config.get(CONF_BASE_LOAD_W, DEFAULT_BASE_LOAD_W),
            off_peak_charge_rate=config.get(CONF_HC_CHARGE_RATE, DEFAULT_HC_CHARGE_RATE),
            max_charge_rate=config.get(CONF_MAX_CHARGE_RATE, DEFAULT_MAX_CHARGE_RATE),
            max_discharge_rate=config.get(CONF_MAX_DISCHARGE_RATE, DEFAULT_MAX_DISCHARGE_RATE),
            surplus_threshold=config.get(CONF_SURPLUS_THRESHOLD, DEFAULT_SURPLUS_THRESHOLD),
            surplus_soc_max=config.get(CONF_SURPLUS_SOC_MAX, DEFAULT_SURPLUS_SOC_MAX),
            discharge_min_power=config.get(CONF_DISCHARGE_MIN_POWER, DEFAULT_DISCHARGE_MIN_POWER),
        )
        self._retry_task: asyncio.Task | None = None

    @property
    def controller(self) -> BatteryController:
        return self._controller

    @property
    def current_mode(self) -> Mode:
        return self._current_mode

    @property
    def last_commanded_power(self) -> int:
        return self._last_commanded_power

    @property
    def target_soc(self) -> int:
        state = self._read_state()
        return compute_target_soc(state.tempo_color, state.solar_forecast_kwh)

    @property
    def reserve_soc(self) -> int:
        state = self._read_state()
        return compute_reserve_soc(
            state.is_off_peak,
            state.hour,
            state.minute,
            self._reg_config.base_load_w,
            state.solar_remaining_kwh,
            self._reg_config.battery_capacity_wh,
        )

    @property
    def battery_power_signed(self) -> int:
        """Battery power with sign based on current mode."""
        power_abs = self._get_sensor_int(self._config[CONF_BATTERY_POWER_SENSOR], 0)
        if self._current_mode in (Mode.CHARGE_SURPLUS, Mode.CHARGE_OFF_PEAK):
            return -power_abs
        elif self._current_mode == Mode.DISCHARGE:
            return power_abs
        else:
            return 0

    def _get_sensor_float(self, entity_id: str, default: float) -> float:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown"):
            return default
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return default

    def _get_sensor_int(self, entity_id: str, default: int) -> int:
        return int(self._get_sensor_float(entity_id, float(default)))

    def _get_sensor_state(self, entity_id: str) -> str | None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown"):
            return None
        return state.state

    def _read_state(self) -> State:
        now_dt = dt_util.now()

        off_peak_state = self._get_sensor_state(self._config[CONF_HC_HP_SENSOR])
        is_off_peak = off_peak_state == "on"

        tempo_entity = self._config.get(CONF_TEMPO_COLOR_SENSOR)
        tempo_color = self._get_sensor_state(tempo_entity) if tempo_entity else None

        return State(
            grid_power=self._get_sensor_int(self._config[CONF_GRID_POWER_SENSOR], 0),
            solar_production=self._get_sensor_int(self._config[CONF_SOLAR_PRODUCTION_SENSOR], 0),
            battery_soc=self._get_sensor_int(self._config[CONF_BATTERY_SOC_SENSOR], 0),
            battery_power_abs=self._get_sensor_int(self._config[CONF_BATTERY_POWER_SENSOR], 0),
            is_off_peak=is_off_peak,
            hour=now_dt.hour,
            minute=now_dt.minute,
            solar_forecast_kwh=self._get_sensor_float(
                self._config[CONF_SOLAR_FORECAST_SENSOR], 0.0
            ),
            solar_remaining_kwh=self._get_sensor_float(
                self._config[CONF_SOLAR_REMAINING_SENSOR], 0.0
            ),
            tempo_color=tempo_color,
        )

    async def _async_update_data(self) -> Decision:
        state = self._read_state()
        decision = regulate(state, self._current_mode, self._reg_config)

        mode_changed = decision.mode != self._current_mode
        power_changed = decision.power != self._last_commanded_power

        if mode_changed:
            # Enforce cooldown on mode changes
            now = dt_util.utcnow()
            elapsed = (now - self._last_mode_change_time).total_seconds()
            if elapsed < MIN_MODE_CHANGE_SECONDS:
                _LOGGER.debug(
                    "Battery regulator: mode change %s -> %s suppressed by cooldown "
                    "(%.0fs < %ds) — %s",
                    self._current_mode.value,
                    decision.mode.value,
                    elapsed,
                    MIN_MODE_CHANGE_SECONDS,
                    decision.reason,
                )
                # Return a decision reflecting the actual current state
                return Decision(
                    mode=self._current_mode,
                    power=self._last_commanded_power,
                    reason=f"cooldown ({decision.reason})",
                )

            _LOGGER.info(
                "Battery regulator: %s -> %s, power=%dW (%s)",
                self._current_mode.value,
                decision.mode.value,
                decision.power,
                decision.reason,
            )
            self._current_mode = decision.mode
            self._last_commanded_power = decision.power
            self._last_mode_change_time = now
            self._cancel_retry()
            await self._send_command_with_retry()
        elif power_changed:
            # Power adjustment within same mode — no cooldown
            _LOGGER.info(
                "Battery regulator: %s power %dW -> %dW (%s)",
                self._current_mode.value,
                self._last_commanded_power,
                decision.power,
                decision.reason,
            )
            self._last_commanded_power = decision.power
            self._cancel_retry()
            await self._send_command_with_retry()
        else:
            _LOGGER.debug(
                "Battery regulator: no change (%s, %dW) — %s",
                decision.mode.value,
                decision.power,
                decision.reason,
            )

        return decision

    async def _send_command(self) -> None:
        """Send the current commanded power to the battery controller."""
        await self._controller.set_power(self._last_commanded_power)

    async def _send_command_with_retry(self) -> None:
        """Try to send the command; on failure, spawn a background retry task."""
        try:
            await self._send_command()
        except Exception:
            _LOGGER.warning(
                "Battery regulator: command failed, scheduling retry (mode=%s, power=%dW)",
                self._current_mode.value,
                self._last_commanded_power,
            )
            self._schedule_retry()

    def _schedule_retry(self) -> None:
        """Schedule a background retry task on the event loop."""
        self._cancel_retry()
        self._retry_task = self.hass.async_create_task(
            self._retry_loop(), "battery_regulator_retry"
        )

    def _cancel_retry(self) -> None:
        """Cancel any pending retry task."""
        if self._retry_task is not None and not self._retry_task.done():
            self._retry_task.cancel()
            self._retry_task = None

    async def _retry_loop(self) -> None:
        """Retry sending the command with backoff.

        Always uses the latest commanded mode/power so that if the regulation
        decision changed between retries, we send the up-to-date command.
        """
        for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
            await asyncio.sleep(RETRY_DELAY_SECONDS)
            try:
                _LOGGER.info(
                    "Battery regulator: retry %d/%d (mode=%s, power=%dW)",
                    attempt,
                    RETRY_MAX_ATTEMPTS,
                    self._current_mode.value,
                    self._last_commanded_power,
                )
                await self._send_command()
                _LOGGER.info("Battery regulator: retry %d succeeded", attempt)
                return
            except Exception:
                _LOGGER.warning(
                    "Battery regulator: retry %d/%d failed",
                    attempt,
                    RETRY_MAX_ATTEMPTS,
                    exc_info=True,
                )
        _LOGGER.error(
            "Battery regulator: all %d retries exhausted (mode=%s, power=%dW)",
            RETRY_MAX_ATTEMPTS,
            self._current_mode.value,
            self._last_commanded_power,
        )
