"""Pure decision logic for battery regulation. No Home Assistant imports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Mode(StrEnum):
    AUTO = "auto"
    CHARGE_SURPLUS = "charge_surplus"
    CHARGE_OFF_PEAK = "charge_off_peak"
    DISCHARGE = "discharge"


@dataclass(frozen=True)
class State:
    grid_power: int  # W, positive=import, negative=export
    solar_production: int  # W
    battery_soc: int  # %
    battery_power_abs: int  # W, absolute value from sensor
    is_off_peak: bool  # True during off-peak hours
    hour: int  # 0-23
    minute: int  # 0-59
    solar_forecast_kwh: float  # Today's forecast in kWh
    solar_remaining_kwh: float  # Remaining today in kWh
    tempo_color: str | None  # "Rouge", "Blanc", "Bleu", or None


@dataclass(frozen=True)
class Config:
    battery_capacity_wh: int  # Battery capacity in Wh
    base_load_w: int  # Base household load in W
    off_peak_charge_rate: int  # Off-peak charge power in W (e.g. 1500)
    max_charge_rate: int  # Max charge power in W (e.g. 2500)
    max_discharge_rate: int  # Max discharge power in W (e.g. 2500)
    surplus_threshold: int  # Grid export threshold to start surplus charging (W, e.g. 100)
    surplus_soc_max: int  # Max SOC for surplus charging (%, e.g. 95)
    discharge_min_power: int  # Min discharge power worth sending (W, e.g. 50)


@dataclass(frozen=True)
class Decision:
    mode: Mode
    power: int  # W, negative=charge, positive=discharge, 0=auto
    reason: str


def compute_target_soc(tempo_color: str | None, solar_forecast_kwh: float) -> int:
    """Compute target SOC for off-peak charging."""
    if tempo_color in ("Rouge", "Blanc"):
        return max(int(100 - solar_forecast_kwh * 2), 60)
    elif tempo_color == "Bleu":
        return max(int(60 - solar_forecast_kwh * 2.5), 20)
    else:
        # No tempo sensor or unknown color — simplified formula
        return max(int(80 - solar_forecast_kwh * 3), 20)


def compute_reserve_soc(
    is_off_peak: bool,
    hour: int,
    minute: int,
    base_load_w: int,
    solar_remaining_kwh: float,
    battery_capacity_wh: int,
) -> int:
    """Compute reserve SOC (minimum to keep for peak loads)."""
    if is_off_peak:
        return 10

    hours_to_off_peak = max(22 - (hour + minute / 60), 0)
    energy_needed_wh = hours_to_off_peak * base_load_w
    solar_remaining_wh = solar_remaining_kwh * 1000
    energy_from_battery_wh = max(energy_needed_wh - solar_remaining_wh, 0)
    reserve = round(energy_from_battery_wh / battery_capacity_wh * 100)
    return max(reserve, 10)


def _signed_battery_power(mode: Mode, power_abs: int) -> int:
    """Return signed battery power based on current mode."""
    if mode == Mode.CHARGE_SURPLUS or mode == Mode.CHARGE_OFF_PEAK:
        return -power_abs
    elif mode == Mode.DISCHARGE:
        return power_abs
    else:
        return 0


def regulate(state: State, current_mode: Mode, config: Config) -> Decision:
    """Main regulation logic. Returns a Decision."""
    target_soc = compute_target_soc(state.tempo_color, state.solar_forecast_kwh)
    reserve_soc = compute_reserve_soc(
        state.is_off_peak,
        state.hour,
        state.minute,
        config.base_load_w,
        state.solar_remaining_kwh,
        config.battery_capacity_wh,
    )

    bat_signed = _signed_battery_power(current_mode, state.battery_power_abs)

    surplus_threshold = config.surplus_threshold
    min_charge = -config.max_charge_rate
    # Minimum charge power — at least 100W or surplus_threshold, whichever is smaller
    max_charge = -min(100, surplus_threshold)

    # Rule 1: Off-peak charging (2am-6am, SOC below target)
    if (
        state.is_off_peak
        and OFF_PEAK_CHARGE_START_HOUR <= state.hour < OFF_PEAK_CHARGE_END_HOUR
        and state.battery_soc < target_soc
    ):
        return Decision(
            mode=Mode.CHARGE_OFF_PEAK,
            power=-config.off_peak_charge_rate,
            reason=(f"Off-peak charge: SOC={state.battery_soc}% < target={target_soc}%"),
        )

    # Rule 2: Stop off-peak charging when target reached
    if (
        current_mode == Mode.CHARGE_OFF_PEAK
        and state.is_off_peak
        and state.battery_soc >= target_soc
    ):
        return Decision(
            mode=Mode.AUTO,
            power=0,
            reason=(f"Off-peak charge complete: SOC={state.battery_soc}% >= target={target_soc}%"),
        )

    # Rule 3: Surplus solar charging
    if (
        state.grid_power < -surplus_threshold
        and state.solar_production > surplus_threshold
        and state.battery_soc < config.surplus_soc_max
    ):
        power = _clamp(
            state.grid_power + bat_signed + CHARGE_SURPLUS_OFFSET,
            min_charge,
            max_charge,
        )
        return Decision(
            mode=Mode.CHARGE_SURPLUS,
            power=power,
            reason=(f"Surplus charge: grid={state.grid_power}W, bat={bat_signed}W, power={power}W"),
        )

    # Rule 4: Peak discharge
    if (
        not state.is_off_peak
        and state.battery_soc > reserve_soc
        and current_mode != Mode.CHARGE_SURPLUS
        and (state.grid_power > DISCHARGE_GRID_OFFSET or current_mode == Mode.DISCHARGE)
        and state.battery_power_abs >= config.discharge_min_power
    ):
        power = _clamp(
            state.grid_power + bat_signed - DISCHARGE_GRID_OFFSET,
            0,
            config.max_discharge_rate,
        )
        if power >= config.discharge_min_power:
            return Decision(
                mode=Mode.DISCHARGE,
                power=power,
                reason=(
                    f"Peak discharge: grid={state.grid_power}W, "
                    f"bat={bat_signed}W, SOC={state.battery_soc}%, "
                    f"reserve={reserve_soc}%, power={power}W"
                ),
            )

    # Rule 5: Stop surplus charging when surplus gone
    if current_mode == Mode.CHARGE_SURPLUS and state.grid_power >= SURPLUS_STOP_GRID_THRESHOLD:
        return Decision(
            mode=Mode.AUTO,
            power=0,
            reason=(f"Surplus gone: grid={state.grid_power}W >= {SURPLUS_STOP_GRID_THRESHOLD}W"),
        )

    # Rule 6: Stop discharging when conditions no longer met
    if current_mode == Mode.DISCHARGE and (
        state.is_off_peak
        or state.battery_soc <= reserve_soc
        or state.battery_power_abs < config.discharge_min_power
    ):
        return Decision(
            mode=Mode.AUTO,
            power=0,
            reason=(
                f"Discharge stop: off_peak={state.is_off_peak}, "
                f"SOC={state.battery_soc}% <= reserve={reserve_soc}%, "
                f"power_abs={state.battery_power_abs}W"
            ),
        )

    # Rule 7: Stop off-peak charging when peak starts
    if current_mode == Mode.CHARGE_OFF_PEAK and not state.is_off_peak:
        return Decision(
            mode=Mode.AUTO,
            power=0,
            reason="Off-peak charge stop: peak started",
        )

    # No change needed — keep current mode
    return Decision(
        mode=current_mode,
        power=0
        if current_mode == Mode.AUTO
        else state.battery_power_abs
        * (-1 if current_mode in (Mode.CHARGE_OFF_PEAK, Mode.CHARGE_SURPLUS) else 1),
        reason="No change",
    )


# Hardcoded constants
OFF_PEAK_CHARGE_START_HOUR = 2
OFF_PEAK_CHARGE_END_HOUR = 6
SURPLUS_STOP_GRID_THRESHOLD = -50
DISCHARGE_GRID_OFFSET = 20
CHARGE_SURPLUS_OFFSET = 100


def _clamp(value: int, min_val: int, max_val: int) -> int:
    return max(min_val, min(max_val, value))
