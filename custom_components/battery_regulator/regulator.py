"""Pure decision logic for battery regulation. No Home Assistant imports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Mode(StrEnum):
    AUTO = "auto"
    SELF_CONSUMPTION = "self_consumption"
    CHARGE_SURPLUS = "charge_surplus"
    CHARGE_OFF_PEAK = "charge_off_peak"
    DISCHARGE = "discharge"


@dataclass(frozen=True)
class State:
    grid_power: int  # W, positive=import, negative=export
    solar_production: int  # W
    battery_soc: int  # %
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
    self_consumption: bool = False  # Use battery's self-consumption mode during peak


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
        return max(int(60 - solar_forecast_kwh * 2.5), 30)
    else:
        # No tempo sensor or unknown color — simplified formula
        return max(int(80 - solar_forecast_kwh * 3), 30)


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
        return 15

    hours_to_off_peak = max(22 - (hour + minute / 60), 0)
    energy_needed_wh = hours_to_off_peak * base_load_w
    solar_remaining_wh = solar_remaining_kwh * 1000
    energy_from_battery_wh = max(energy_needed_wh - solar_remaining_wh, 0)
    reserve = round(energy_from_battery_wh / battery_capacity_wh * 100)
    return max(reserve, 15)


OFF_PEAK_CHARGE_START_HOUR = 2
OFF_PEAK_CHARGE_END_HOUR = 6


def regulate(
    state: State,
    bat_signed: int,
    config: Config,
) -> Decision:
    """Feedback-loop regulation: compute battery target power to zero out grid.

    Args:
        state: Current sensor readings.
        bat_signed: Signed battery power (negative=charging, positive=discharging).
            Computed by the coordinator using last_commanded_power sign.
        config: Battery configuration parameters.

    Returns:
        Decision with target power and derived mode label.
    """
    target_soc = compute_target_soc(state.tempo_color, state.solar_forecast_kwh)
    reserve_soc = compute_reserve_soc(
        state.is_off_peak,
        state.hour,
        state.minute,
        config.base_load_w,
        state.solar_remaining_kwh,
        config.battery_capacity_wh,
    )

    # Off-peak grid charging (2am-6am, SOC below target)
    if (
        state.is_off_peak
        and OFF_PEAK_CHARGE_START_HOUR <= state.hour < OFF_PEAK_CHARGE_END_HOUR
        and state.battery_soc < target_soc
    ):
        return Decision(
            mode=Mode.CHARGE_OFF_PEAK,
            power=-config.off_peak_charge_rate,
            reason=f"Off-peak charge: SOC={state.battery_soc}% < target={target_soc}%",
        )

    # Off-peak hold: outside charge window, SOC at target — hold charge for peak hours
    if (
        state.is_off_peak
        and not (OFF_PEAK_CHARGE_START_HOUR <= state.hour < OFF_PEAK_CHARGE_END_HOUR)
        and state.battery_soc <= target_soc
    ):
        return Decision(
            mode=Mode.AUTO,
            power=0,
            reason=(
                f"Off-peak hold: SOC={state.battery_soc}% >= target={target_soc}%, "
                f"holding charge for peak"
            ),
        )

    # Self-consumption: let battery handle grid-zeroing autonomously
    if config.self_consumption:
        return Decision(
            mode=Mode.SELF_CONSUMPTION,
            power=0,
            reason=(
                f"Self-consumption: SOC={state.battery_soc}%, "
                f"reserve={reserve_soc}%, target_soc={target_soc}%"
            ),
        )

    # Feedback: zero out grid
    target = bat_signed + state.grid_power

    # Clamp to battery rate limits
    target = _clamp(target, -config.max_charge_rate, config.max_discharge_rate)

    # SOC floor: don't discharge below reserve or off-peak target
    if state.battery_soc <= reserve_soc or (state.is_off_peak and state.battery_soc <= target_soc):
        target = min(target, 0)

    # SOC ceiling: don't charge above max
    if state.battery_soc >= config.surplus_soc_max:
        target = max(target, 0)

    # Surplus charging: never charge more than solar produces
    # (prevents grid import from feedback overshoot during Marstek settling)
    is_hc_charge = (
        state.is_off_peak and OFF_PEAK_CHARGE_START_HOUR <= state.hour < OFF_PEAK_CHARGE_END_HOUR
    )
    if target < 0 and not is_hc_charge:
        target = max(target, -state.solar_production)

    # Dead band: tiny discharge not worth sending
    if 0 < target < config.discharge_min_power:
        target = 0

    # Derive mode label from power (display only)
    if target < 0:
        mode = Mode.CHARGE_SURPLUS
    elif target > 0:
        mode = Mode.DISCHARGE
    else:
        mode = Mode.AUTO

    return Decision(
        mode=mode,
        power=target,
        reason=(
            f"Feedback: grid={state.grid_power}W, bat={bat_signed}W, "
            f"target={target}W, SOC={state.battery_soc}%, "
            f"reserve={reserve_soc}%, target_soc={target_soc}%"
        ),
    )


def _clamp(value: int, min_val: int, max_val: int) -> int:
    return max(min_val, min(max_val, value))
