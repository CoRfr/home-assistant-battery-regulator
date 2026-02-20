"""Pure decision logic for battery regulation. No Home Assistant imports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Mode(str, Enum):
    AUTO = "auto"
    CHARGE_SURPLUS = "charge_surplus"
    CHARGE_HC = "charge_hc"
    DISCHARGE = "discharge"


@dataclass(frozen=True)
class State:
    grid_power: int  # W, positive=import, negative=export
    solar_production: int  # W
    battery_soc: int  # %
    battery_power_abs: int  # W, absolute value from sensor
    is_hc: bool  # True during heures creuses
    hour: int  # 0-23
    minute: int  # 0-59
    solar_forecast_kwh: float  # Today's forecast in kWh
    solar_remaining_kwh: float  # Remaining today in kWh
    tempo_color: str | None  # "Rouge", "Blanc", "Bleu", or None


@dataclass(frozen=True)
class Config:
    battery_capacity_wh: int
    base_load_w: int


@dataclass(frozen=True)
class Decision:
    mode: Mode
    power: int  # W, negative=charge, positive=discharge, 0=auto
    reason: str


def compute_target_soc(tempo_color: str | None, solar_forecast_kwh: float) -> int:
    """Compute target SOC for HC charging."""
    if tempo_color in ("Rouge", "Blanc"):
        return max(int(100 - solar_forecast_kwh * 2), 60)
    elif tempo_color == "Bleu":
        return max(int(60 - solar_forecast_kwh * 2.5), 20)
    else:
        # No tempo sensor or unknown color — simplified formula
        return max(int(80 - solar_forecast_kwh * 3), 20)


def compute_reserve_soc(
    is_hc: bool,
    hour: int,
    minute: int,
    base_load_w: int,
    solar_remaining_kwh: float,
    battery_capacity_wh: int,
) -> int:
    """Compute reserve SOC (minimum to keep for HP loads)."""
    if is_hc:
        return 10

    hours_to_hc = max(22 - (hour + minute / 60), 0)
    energy_needed_wh = hours_to_hc * base_load_w
    solar_remaining_wh = solar_remaining_kwh * 1000
    energy_from_battery_wh = max(energy_needed_wh - solar_remaining_wh, 0)
    reserve = round(energy_from_battery_wh / battery_capacity_wh * 100)
    return max(reserve, 10)


def _signed_battery_power(mode: Mode, power_abs: int) -> int:
    """Return signed battery power based on current mode."""
    if mode == Mode.CHARGE_SURPLUS or mode == Mode.CHARGE_HC:
        return -power_abs
    elif mode == Mode.DISCHARGE:
        return power_abs
    else:
        return 0


def regulate(state: State, current_mode: Mode, config: Config) -> Decision:
    """Main regulation logic. Returns a Decision."""
    target_soc = compute_target_soc(state.tempo_color, state.solar_forecast_kwh)
    reserve_soc = compute_reserve_soc(
        state.is_hc,
        state.hour,
        state.minute,
        config.base_load_w,
        state.solar_remaining_kwh,
        config.battery_capacity_wh,
    )

    bat_signed = _signed_battery_power(current_mode, state.battery_power_abs)

    # Rule 1: HC charging (2am-6am, SOC below target)
    if (
        state.is_hc
        and HC_CHARGE_START_HOUR <= state.hour < HC_CHARGE_END_HOUR
        and state.battery_soc < target_soc
    ):
        return Decision(
            mode=Mode.CHARGE_HC,
            power=-1500,
            reason=(
                f"HC charge: SOC={state.battery_soc}% < target={target_soc}%"
            ),
        )

    # Rule 2: Stop HC charging when target reached
    if (
        current_mode == Mode.CHARGE_HC
        and state.is_hc
        and state.battery_soc >= target_soc
    ):
        return Decision(
            mode=Mode.AUTO,
            power=0,
            reason=(
                f"HC charge complete: SOC={state.battery_soc}% >= target={target_soc}%"
            ),
        )

    # Rule 3: Surplus solar charging
    if (
        state.grid_power < -100
        and state.solar_production > 100
        and state.battery_soc < 95
    ):
        power = _clamp(
            state.grid_power + bat_signed + 100,
            -2500,
            -100,
        )
        return Decision(
            mode=Mode.CHARGE_SURPLUS,
            power=power,
            reason=(
                f"Surplus charge: grid={state.grid_power}W, "
                f"bat={bat_signed}W, power={power}W"
            ),
        )

    # Rule 4: HP discharge
    if (
        not state.is_hc
        and state.battery_soc > reserve_soc
        and current_mode != Mode.CHARGE_SURPLUS
        and (state.grid_power > 20 or current_mode == Mode.DISCHARGE)
        and state.battery_power_abs >= 50
    ):
        power = _clamp(
            state.grid_power + bat_signed - 20,
            0,
            2500,
        )
        if power >= 50:
            return Decision(
                mode=Mode.DISCHARGE,
                power=power,
                reason=(
                    f"HP discharge: grid={state.grid_power}W, "
                    f"bat={bat_signed}W, SOC={state.battery_soc}%, "
                    f"reserve={reserve_soc}%, power={power}W"
                ),
            )

    # Rule 5: Stop surplus charging when surplus gone
    if (
        current_mode == Mode.CHARGE_SURPLUS
        and state.grid_power >= -50
    ):
        return Decision(
            mode=Mode.AUTO,
            power=0,
            reason=(
                f"Surplus gone: grid={state.grid_power}W >= -50W"
            ),
        )

    # Rule 6: Stop discharging when conditions no longer met
    if current_mode == Mode.DISCHARGE and (
        state.is_hc
        or state.battery_soc <= reserve_soc
        or state.battery_power_abs < 50
    ):
        return Decision(
            mode=Mode.AUTO,
            power=0,
            reason=(
                f"Discharge stop: HC={state.is_hc}, "
                f"SOC={state.battery_soc}% <= reserve={reserve_soc}%, "
                f"power_abs={state.battery_power_abs}W"
            ),
        )

    # Rule 7: Stop HC charging when HP starts
    if current_mode == Mode.CHARGE_HC and not state.is_hc:
        return Decision(
            mode=Mode.AUTO,
            power=0,
            reason="HC charge stop: HP started",
        )

    # No change needed — keep current mode
    return Decision(
        mode=current_mode,
        power=0 if current_mode == Mode.AUTO else state.battery_power_abs * (-1 if current_mode in (Mode.CHARGE_HC, Mode.CHARGE_SURPLUS) else 1),
        reason="No change",
    )


# Constants used in rules
HC_CHARGE_START_HOUR = 2
HC_CHARGE_END_HOUR = 6


def _clamp(value: int, min_val: int, max_val: int) -> int:
    return max(min_val, min(max_val, value))
