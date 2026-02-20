"""Unit tests for coordinator cooldown and set_power logic.

Uses lightweight mocks — no Home Assistant runtime required.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: set up HA stubs so the coordinator module can be imported
# as part of the battery_regulator package (with relative imports working).
# ---------------------------------------------------------------------------

# 1. Stub homeassistant modules
_ha_stubs = {}
for mod in [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.util",
    "homeassistant.util.dt",
]:
    _ha_stubs[mod] = sys.modules.setdefault(mod, MagicMock())


# 2. Make DataUpdateCoordinator a real (empty) base so the class can inherit
class _StubDataUpdateCoordinator:
    def __init__(self, *a, **kw):
        pass

    def __class_getitem__(cls, item):
        return cls


sys.modules[
    "homeassistant.helpers.update_coordinator"
].DataUpdateCoordinator = _StubDataUpdateCoordinator

# 3. Import the package properly so relative imports work
_pkg_root = Path(__file__).resolve().parent.parent / "custom_components"
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from battery_regulator.const import MIN_MODE_CHANGE_SECONDS  # noqa: E402
from battery_regulator.coordinator import BatteryRegulatorCoordinator  # noqa: E402
from battery_regulator.regulator import Config, Decision, Mode  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_REG_CONFIG = Config(
    battery_capacity_wh=5120,
    base_load_w=400,
    off_peak_charge_rate=1500,
    max_charge_rate=2500,
    max_discharge_rate=2500,
    surplus_threshold=100,
    surplus_soc_max=95,
    discharge_min_power=50,
)

# Module path for patching
_COORD_MOD = "battery_regulator.coordinator"


def _make_coordinator(
    controller: AsyncMock | None = None,
) -> BatteryRegulatorCoordinator:
    """Build a coordinator with mocked HA plumbing."""
    hass = MagicMock()
    hass.states = MagicMock()
    hass.async_create_task = MagicMock(return_value=MagicMock(done=MagicMock(return_value=True)))

    config = {
        "grid_power_sensor": "sensor.grid",
        "solar_production_sensor": "sensor.solar",
        "battery_soc_sensor": "sensor.soc",
        "battery_power_sensor": "sensor.bat_power",
        "hc_hp_sensor": "sensor.hc",
        "solar_forecast_sensor": "sensor.forecast",
        "solar_remaining_sensor": "sensor.remaining",
    }

    if controller is None:
        controller = AsyncMock()
        controller.set_power = AsyncMock()

    # Bypass DataUpdateCoordinator.__init__
    coord = object.__new__(BatteryRegulatorCoordinator)
    coord.hass = hass
    coord._config = config
    coord._controller = controller
    coord._current_mode = Mode.AUTO
    coord._last_commanded_power = 0
    coord._last_mode_change_time = datetime.now(tz=UTC) - timedelta(seconds=120)
    coord._reg_config = DEFAULT_REG_CONFIG
    coord._retry_task = None
    coord.logger = MagicMock()
    return coord


# ---------------------------------------------------------------------------
# Tests: mode change cooldown
# ---------------------------------------------------------------------------


class TestModeChangeCooldown:
    """Verify the MIN_MODE_CHANGE_SECONDS cooldown between mode transitions."""

    @pytest.mark.asyncio
    async def test_mode_change_allowed_after_cooldown(self):
        coord = _make_coordinator()
        coord._current_mode = Mode.AUTO
        now = datetime.now(tz=UTC)
        coord._last_mode_change_time = now - timedelta(seconds=MIN_MODE_CHANGE_SECONDS + 1)

        decision = Decision(mode=Mode.DISCHARGE, power=500, reason="test")

        with (
            patch(f"{_COORD_MOD}.regulate", return_value=decision),
            patch(f"{_COORD_MOD}.dt_util") as mock_dt,
        ):
            mock_dt.utcnow.return_value = now
            mock_dt.now.return_value = now
            result = await coord._async_update_data()

        assert result.mode == Mode.DISCHARGE
        assert coord._current_mode == Mode.DISCHARGE
        assert coord._last_commanded_power == 500
        coord._controller.set_power.assert_awaited_once_with(500)

    @pytest.mark.asyncio
    async def test_mode_change_suppressed_during_cooldown(self):
        coord = _make_coordinator()
        coord._current_mode = Mode.AUTO
        now = datetime.now(tz=UTC)
        coord._last_mode_change_time = now - timedelta(seconds=5)

        decision = Decision(mode=Mode.DISCHARGE, power=500, reason="test")

        with (
            patch(f"{_COORD_MOD}.regulate", return_value=decision),
            patch(f"{_COORD_MOD}.dt_util") as mock_dt,
        ):
            mock_dt.utcnow.return_value = now
            mock_dt.now.return_value = now
            result = await coord._async_update_data()

        assert coord._current_mode == Mode.AUTO
        assert result.mode == Mode.AUTO
        assert "cooldown" in result.reason
        coord._controller.set_power.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cooldown_exact_boundary(self):
        coord = _make_coordinator()
        coord._current_mode = Mode.AUTO
        now = datetime.now(tz=UTC)
        coord._last_mode_change_time = now - timedelta(seconds=MIN_MODE_CHANGE_SECONDS)

        decision = Decision(mode=Mode.DISCHARGE, power=500, reason="test")

        with (
            patch(f"{_COORD_MOD}.regulate", return_value=decision),
            patch(f"{_COORD_MOD}.dt_util") as mock_dt,
        ):
            mock_dt.utcnow.return_value = now
            mock_dt.now.return_value = now
            result = await coord._async_update_data()

        assert result.mode == Mode.DISCHARGE
        assert coord._current_mode == Mode.DISCHARGE

    @pytest.mark.asyncio
    async def test_cooldown_updates_last_mode_change_time(self):
        coord = _make_coordinator()
        coord._current_mode = Mode.AUTO
        now = datetime.now(tz=UTC)
        coord._last_mode_change_time = now - timedelta(seconds=60)

        decision = Decision(mode=Mode.DISCHARGE, power=500, reason="test")

        with (
            patch(f"{_COORD_MOD}.regulate", return_value=decision),
            patch(f"{_COORD_MOD}.dt_util") as mock_dt,
        ):
            mock_dt.utcnow.return_value = now
            mock_dt.now.return_value = now
            await coord._async_update_data()

        assert coord._last_mode_change_time == now

    @pytest.mark.asyncio
    async def test_suppressed_mode_change_preserves_last_change_time(self):
        coord = _make_coordinator()
        coord._current_mode = Mode.AUTO
        now = datetime.now(tz=UTC)
        original_time = now - timedelta(seconds=10)
        coord._last_mode_change_time = original_time

        decision = Decision(mode=Mode.DISCHARGE, power=500, reason="test")

        with (
            patch(f"{_COORD_MOD}.regulate", return_value=decision),
            patch(f"{_COORD_MOD}.dt_util") as mock_dt,
        ):
            mock_dt.utcnow.return_value = now
            mock_dt.now.return_value = now
            await coord._async_update_data()

        # Last mode change time should NOT have been updated
        assert coord._last_mode_change_time == original_time


class TestPowerChangeWithinSameMode:
    @pytest.mark.asyncio
    async def test_power_change_no_cooldown(self):
        coord = _make_coordinator()
        coord._current_mode = Mode.DISCHARGE
        coord._last_commanded_power = 400
        now = datetime.now(tz=UTC)
        coord._last_mode_change_time = now - timedelta(seconds=5)

        decision = Decision(mode=Mode.DISCHARGE, power=600, reason="adjust")

        with (
            patch(f"{_COORD_MOD}.regulate", return_value=decision),
            patch(f"{_COORD_MOD}.dt_util") as mock_dt,
        ):
            mock_dt.utcnow.return_value = now
            mock_dt.now.return_value = now
            result = await coord._async_update_data()

        assert result.mode == Mode.DISCHARGE
        assert result.power == 600
        assert coord._last_commanded_power == 600
        coord._controller.set_power.assert_awaited_once_with(600)


class TestSendCommand:
    @pytest.mark.asyncio
    async def test_send_command_calls_set_power(self):
        coord = _make_coordinator()
        coord._last_commanded_power = -1500
        await coord._send_command()
        coord._controller.set_power.assert_awaited_once_with(-1500)

    @pytest.mark.asyncio
    async def test_send_command_zero_for_idle(self):
        coord = _make_coordinator()
        coord._current_mode = Mode.AUTO
        coord._last_commanded_power = 0
        await coord._send_command()
        coord._controller.set_power.assert_awaited_once_with(0)


class TestNoChangeSkipsCommand:
    @pytest.mark.asyncio
    async def test_no_change(self):
        coord = _make_coordinator()
        coord._current_mode = Mode.DISCHARGE
        coord._last_commanded_power = 500

        decision = Decision(mode=Mode.DISCHARGE, power=500, reason="steady")

        with (
            patch(f"{_COORD_MOD}.regulate", return_value=decision),
            patch(f"{_COORD_MOD}.dt_util") as mock_dt,
        ):
            now = datetime.now(tz=UTC)
            mock_dt.utcnow.return_value = now
            mock_dt.now.return_value = now
            result = await coord._async_update_data()

        assert result.mode == Mode.DISCHARGE
        coord._controller.set_power.assert_not_awaited()
