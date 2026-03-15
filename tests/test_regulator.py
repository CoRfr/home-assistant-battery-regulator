"""Unit tests for battery_regulator.regulator — pure Python, no HA deps."""

from regulator import (
    Config,
    Mode,
    State,
    compute_reserve_soc,
    compute_target_soc,
    regulate,
)

DEFAULT_CONFIG = Config(
    battery_capacity_wh=5120,
    base_load_w=400,
    off_peak_charge_rate=1500,
    max_charge_rate=2500,
    max_discharge_rate=2500,
    surplus_threshold=100,
    surplus_soc_max=95,
    discharge_min_power=50,
)

SELF_CONSUMPTION_CONFIG = Config(
    battery_capacity_wh=5120,
    base_load_w=400,
    off_peak_charge_rate=1500,
    max_charge_rate=2500,
    max_discharge_rate=2500,
    surplus_threshold=100,
    surplus_soc_max=95,
    discharge_min_power=50,
    self_consumption=True,
)


def make_state(**overrides) -> State:
    defaults = dict(
        grid_power=0,
        solar_production=0,
        battery_soc=50,
        is_off_peak=False,
        hour=14,
        minute=0,
        solar_forecast_kwh=5.0,
        solar_remaining_kwh=2.0,
        tempo_color="Bleu",
    )
    defaults.update(overrides)
    return State(**defaults)


# --- compute_target_soc ---


class TestComputeTargetSoc:
    def test_rouge_no_solar(self):
        assert compute_target_soc("Rouge", 0.0) == 100

    def test_rouge_high_solar(self):
        assert compute_target_soc("Rouge", 20.0) == 60  # clamped

    def test_rouge_mid_solar(self):
        assert compute_target_soc("Rouge", 10.0) == 80

    def test_blanc_same_as_rouge(self):
        assert compute_target_soc("Blanc", 5.0) == 90

    def test_bleu_no_solar(self):
        assert compute_target_soc("Bleu", 0.0) == 60

    def test_bleu_high_solar(self):
        assert compute_target_soc("Bleu", 16.0) == 30  # clamped

    def test_bleu_mid_solar(self):
        assert compute_target_soc("Bleu", 8.0) == 40

    def test_no_tempo(self):
        # Simplified formula: max(80 - forecast*3, 20)
        assert compute_target_soc(None, 0.0) == 80
        assert compute_target_soc(None, 20.0) == 30  # clamped


# --- compute_reserve_soc ---


class TestComputeReserveSoc:
    def test_off_peak_always_15(self):
        assert compute_reserve_soc(True, 3, 0, 400, 5.0, 5120) == 15

    def test_peak_early_morning_high_reserve(self):
        # 8am, 14h to off-peak, 400W base, no solar remaining
        reserve = compute_reserve_soc(False, 8, 0, 400, 0.0, 5120)
        expected = round(14 * 400 / 5120 * 100)
        assert reserve == expected  # ~109% -> clamped by caller if needed

    def test_peak_with_solar_reduces_reserve(self):
        # 14:00, 8h to off-peak, 400W base, 2kWh solar remaining
        # energy_needed = 8*400 = 3200, from_battery = max(3200-2000, 0) = 1200
        reserve = compute_reserve_soc(False, 14, 0, 400, 2.0, 5120)
        assert reserve == round(1200 / 5120 * 100)  # ~23%

    def test_peak_late_evening_low_reserve(self):
        # 21:00, 1h to off-peak, round(1*400/5120*100) ~= 8% -> clamped to min 15
        reserve = compute_reserve_soc(False, 21, 0, 400, 0.0, 5120)
        assert reserve == 15

    def test_after_22_zero_hours(self):
        # 22:30 -> hours_to_off_peak = max(22 - 22.5, 0) = 0
        reserve = compute_reserve_soc(False, 22, 30, 400, 0.0, 5120)
        assert reserve == 15  # min


# --- regulate: feedback loop basics ---


class TestFeedbackLoop:
    def test_zero_grid_zero_bat_gives_auto(self):
        """No grid import/export and idle battery -> target=0 -> AUTO."""
        state = make_state(grid_power=0, battery_soc=50)
        decision = regulate(state, 0, DEFAULT_CONFIG)
        assert decision.mode == Mode.AUTO
        assert decision.power == 0

    def test_grid_import_starts_discharge(self):
        """Grid importing 500W with idle battery -> target=500W discharge."""
        state = make_state(grid_power=500, battery_soc=60, hour=19, solar_remaining_kwh=0.0)
        decision = regulate(state, 0, DEFAULT_CONFIG)
        assert decision.mode == Mode.DISCHARGE
        assert decision.power == 500

    def test_grid_export_starts_charge(self):
        """Grid exporting 500W with idle battery -> target=-500W charge."""
        state = make_state(grid_power=-500, solar_production=600, battery_soc=50)
        decision = regulate(state, 0, DEFAULT_CONFIG)
        assert decision.mode == Mode.CHARGE_SURPLUS
        assert decision.power == -500

    def test_adjusts_with_existing_discharge(self):
        """Battery already discharging 400W, grid still importing 100W -> target=500W."""
        state = make_state(grid_power=100, battery_soc=60, hour=19, solar_remaining_kwh=0.0)
        decision = regulate(state, 400, DEFAULT_CONFIG)
        assert decision.mode == Mode.DISCHARGE
        assert decision.power == 500

    def test_adjusts_with_existing_charge(self):
        """Battery already charging 500W, grid still exporting 200W -> target=-700W."""
        state = make_state(grid_power=-200, solar_production=800, battery_soc=50)
        decision = regulate(state, -500, DEFAULT_CONFIG)
        assert decision.mode == Mode.CHARGE_SURPLUS
        assert decision.power == -700

    def test_reduces_discharge_when_grid_negative(self):
        """Battery discharging 600W, grid at -575W -> target=25W, below min -> 0."""
        state = make_state(
            grid_power=-575, battery_soc=60, hour=17, minute=50, solar_remaining_kwh=0.0
        )
        decision = regulate(state, 600, DEFAULT_CONFIG)
        # target = 600 + (-575) = 25, < 50 min -> 0
        assert decision.mode == Mode.AUTO
        assert decision.power == 0

    def test_clamp_discharge_to_max(self):
        """Grid importing 3000W -> clamped to max_discharge_rate."""
        state = make_state(grid_power=3000, battery_soc=80, hour=14, solar_remaining_kwh=0.0)
        decision = regulate(state, 0, DEFAULT_CONFIG)
        assert decision.power == 2500

    def test_clamp_charge_to_max(self):
        """Grid exporting 3000W -> clamped to -max_charge_rate."""
        state = make_state(grid_power=-3000, solar_production=4000, battery_soc=50)
        decision = regulate(state, 0, DEFAULT_CONFIG)
        assert decision.power == -2500


# --- regulate: off-peak charging ---


class TestRegulateOffPeakCharge:
    def test_off_peak_charge_starts(self):
        state = make_state(is_off_peak=True, hour=3, battery_soc=30, tempo_color="Bleu")
        decision = regulate(state, 0, DEFAULT_CONFIG)
        assert decision.mode == Mode.CHARGE_OFF_PEAK
        assert decision.power == -1500

    def test_off_peak_charge_not_before_2am(self):
        state = make_state(is_off_peak=True, hour=1, battery_soc=30, tempo_color="Bleu")
        decision = regulate(state, 0, DEFAULT_CONFIG)
        assert decision.mode != Mode.CHARGE_OFF_PEAK

    def test_off_peak_charge_not_after_6am(self):
        state = make_state(is_off_peak=True, hour=6, battery_soc=30, tempo_color="Bleu")
        decision = regulate(state, 0, DEFAULT_CONFIG)
        assert decision.mode != Mode.CHARGE_OFF_PEAK

    def test_off_peak_charge_stops_at_target(self):
        # Target for Bleu with 5kWh forecast = max(60 - 12, 20) = 48
        state = make_state(
            is_off_peak=True,
            hour=3,
            battery_soc=48,
            solar_forecast_kwh=5.0,
            tempo_color="Bleu",
        )
        decision = regulate(state, -1500, DEFAULT_CONFIG)
        assert decision.mode != Mode.CHARGE_OFF_PEAK

    def test_off_peak_charge_retries_when_below_target(self):
        state = make_state(is_off_peak=True, hour=4, battery_soc=40, tempo_color="Bleu")
        decision = regulate(state, -1500, DEFAULT_CONFIG)
        assert decision.mode == Mode.CHARGE_OFF_PEAK
        assert decision.power == -1500

    def test_off_peak_charge_stops_when_peak_starts(self):
        """Outside off-peak, the off-peak charge rule doesn't trigger.
        Feedback loop takes over — with no grid import, target=0."""
        state = make_state(is_off_peak=False, hour=7, battery_soc=40, tempo_color="Bleu")
        decision = regulate(state, -1500, DEFAULT_CONFIG)
        # bat_signed=-1500, grid=0 -> target = -1500 + 0 = -1500 (charge)
        # But this is feedback, not off-peak charge
        assert decision.mode != Mode.CHARGE_OFF_PEAK


# --- regulate: SOC limits ---


class TestSOCLimits:
    def test_no_discharge_below_reserve(self):
        """SOC at reserve -> discharge clamped to 0."""
        state = make_state(
            grid_power=500,
            battery_soc=15,
            hour=21,
            solar_remaining_kwh=0.0,
        )
        # reserve at 21:00 = max(round(1*400/5120*100), 15) = 15
        # SOC=15 <= reserve=15 -> target clamped to min(target, 0)
        decision = regulate(state, 0, DEFAULT_CONFIG)
        assert decision.power <= 0

    def test_no_charge_above_soc_max(self):
        """SOC at surplus_soc_max -> charge clamped to 0."""
        state = make_state(
            grid_power=-500,
            solar_production=600,
            battery_soc=95,
        )
        decision = regulate(state, 0, DEFAULT_CONFIG)
        assert decision.power >= 0

    def test_off_peak_no_discharge_below_target(self):
        """During off-peak, don't discharge below target_soc."""
        state = make_state(
            grid_power=500,
            battery_soc=30,
            is_off_peak=True,
            hour=22,
            tempo_color="Bleu",
            solar_forecast_kwh=5.0,
        )
        # target_soc for Bleu with 5kWh = max(60-12, 20) = 48
        # SOC=30 <= target=48 -> target clamped to min(target, 0)
        decision = regulate(state, 0, DEFAULT_CONFIG)
        assert decision.power <= 0


# --- regulate: dead band ---


class TestDeadBand:
    def test_tiny_discharge_becomes_zero(self):
        """Discharge below min_power -> 0."""
        state = make_state(
            grid_power=30,
            battery_soc=60,
            hour=14,
            solar_remaining_kwh=0.0,
        )
        decision = regulate(state, 0, DEFAULT_CONFIG)
        # target = 0 + 30 = 30, < 50 -> 0
        assert decision.power == 0
        assert decision.mode == Mode.AUTO


# --- regulate: priority / edge cases ---


class TestRegulatePriority:
    def test_off_peak_charge_overrides_feedback(self):
        """During off-peak 2-6am with low SOC, off-peak charge takes priority."""
        state = make_state(
            is_off_peak=True,
            hour=3,
            battery_soc=30,
            grid_power=-500,
            solar_production=600,
            tempo_color="Bleu",
        )
        decision = regulate(state, 0, DEFAULT_CONFIG)
        assert decision.mode == Mode.CHARGE_OFF_PEAK

    def test_idle_gives_auto(self):
        """No grid import/export -> AUTO."""
        state = make_state(
            grid_power=5,
            solar_production=0,
            battery_soc=50,
            is_off_peak=False,
            hour=14,
        )
        decision = regulate(state, 0, DEFAULT_CONFIG)
        # target = 0 + 5 = 5, < 50 dead band -> 0
        assert decision.mode == Mode.AUTO

    def test_live_snapshot_surplus_charging(self):
        """Snapshot of live sensor state at 2026-02-20 14:00.

        Grid exporting 443W, solar 559W, battery barely active.
        Feedback: target = bat_signed + grid = -8 + (-443) = -451
        """
        state = State(
            grid_power=-443,
            solar_production=559,
            battery_soc=52,
            is_off_peak=False,
            hour=14,
            minute=0,
            solar_forecast_kwh=9.124,
            solar_remaining_kwh=3.668,
            tempo_color="Bleu",
        )

        # Already charging at -8W (nearly idle)
        decision = regulate(state, -8, DEFAULT_CONFIG)
        assert decision.mode == Mode.CHARGE_SURPLUS
        assert decision.power == -451

        # From idle
        decision_fresh = regulate(state, 0, DEFAULT_CONFIG)
        assert decision_fresh.mode == Mode.CHARGE_SURPLUS
        assert decision_fresh.power == -443

    def test_surplus_during_off_peak_outside_charge_window(self):
        """Off-peak outside 2-6am, SOC below target -> feedback charges normally."""
        state = make_state(
            is_off_peak=True,
            hour=22,
            battery_soc=20,
            grid_power=-500,
            solar_production=600,
            tempo_color="Rouge",  # target_soc = 90, so SOC 20 < 90 -> no hold
        )
        decision = regulate(state, 0, DEFAULT_CONFIG)
        assert decision.mode == Mode.CHARGE_SURPLUS
        assert decision.power == -500

    def test_discharge_from_idle_battery(self):
        """Discharge starts even when battery is idle (power near zero).

        Snapshot from 2026-02-20 ~16:47 UTC: grid=600W, SOC=57%, idle.
        """
        state = make_state(
            grid_power=600,
            battery_soc=57,
            is_off_peak=False,
            hour=17,
            minute=47,
            solar_production=87,
            solar_remaining_kwh=0.0,
        )
        decision = regulate(state, 0, DEFAULT_CONFIG)
        assert decision.mode == Mode.DISCHARGE
        assert decision.power == 600

    def test_over_discharge_reduces_smoothly(self):
        """Battery over-discharging (grid negative) -> feedback reduces target.

        Snapshot from 2026-02-21 09:20. Battery discharging 961W,
        grid at -151W. Feedback: target = 961 + (-151) = 810W.
        """
        state = make_state(
            grid_power=-151,
            solar_production=340,
            battery_soc=26,
            is_off_peak=False,
            hour=9,
            minute=20,
            solar_remaining_kwh=8.0,
        )
        decision = regulate(state, 961, DEFAULT_CONFIG)
        assert decision.mode == Mode.DISCHARGE
        assert decision.power == 810

    def test_surplus_clamp_prevents_grid_import(self):
        """Feedback overshoot clamped to solar production.

        Scenario: battery commanded to -600W but Marstek hasn't responded,
        grid still exporting 600W. Without clamp, target = -600 + (-600) = -1200W
        which would import 600W from grid once Marstek catches up.
        With clamp, target capped at -solar_production = -700W.
        """
        state = make_state(
            grid_power=-600,
            solar_production=700,
            battery_soc=50,
            is_off_peak=False,
            hour=12,
        )
        decision = regulate(state, -600, DEFAULT_CONFIG)
        assert decision.power == -700  # clamped to solar, not -1200

    def test_surplus_clamp_zero_solar_stops_charge(self):
        """No solar -> no surplus charging, even if feedback says charge."""
        state = make_state(
            grid_power=0,
            solar_production=0,
            battery_soc=50,
            is_off_peak=False,
            hour=14,
        )
        decision = regulate(state, -500, DEFAULT_CONFIG)
        # target = -500 + 0 = -500, clamped to max(-500, 0) = 0
        assert decision.power == 0

    def test_surplus_clamp_does_not_affect_off_peak(self):
        """Off-peak 2-6am charging is NOT clamped to solar."""
        state = make_state(
            is_off_peak=True,
            hour=3,
            battery_soc=30,
            solar_production=0,
            tempo_color="Bleu",
        )
        decision = regulate(state, 0, DEFAULT_CONFIG)
        assert decision.mode == Mode.CHARGE_OFF_PEAK
        assert decision.power == -1500


class TestOffPeakHold:
    def test_off_peak_hold_soc_at_target(self):
        """Off-peak outside charge window, SOC >= target -> hold charge."""
        state = make_state(
            is_off_peak=True,
            hour=23,
            battery_soc=50,
            grid_power=300,  # grid importing, but we hold anyway
        )
        decision = regulate(state, 0, DEFAULT_CONFIG)
        assert decision.mode == Mode.AUTO
        assert decision.power == 0
        assert "hold" in decision.reason.lower()

    def test_off_peak_hold_does_not_apply_during_charge_window(self):
        """During 2-6am charge window, off-peak charge takes priority."""
        state = make_state(
            is_off_peak=True,
            hour=3,
            battery_soc=30,
            tempo_color="Bleu",
        )
        decision = regulate(state, 0, DEFAULT_CONFIG)
        assert decision.mode == Mode.CHARGE_OFF_PEAK

    def test_off_peak_hold_does_not_apply_below_target(self):
        """Off-peak outside charge window, SOC < target -> feedback loop."""
        state = make_state(
            is_off_peak=True,
            hour=22,
            battery_soc=20,
            grid_power=0,
            tempo_color="Rouge",  # target_soc = 90
        )
        decision = regulate(state, 0, DEFAULT_CONFIG)
        # Falls through to feedback loop, not hold
        assert decision.mode == Mode.AUTO  # grid=0, bat=0 -> target=0
        assert decision.power == 0

    def test_off_peak_hold_does_not_apply_during_peak(self):
        """Peak hours -> normal feedback loop, no hold."""
        state = make_state(
            is_off_peak=False,
            hour=14,
            battery_soc=80,
            grid_power=500,
        )
        decision = regulate(state, 0, DEFAULT_CONFIG)
        assert decision.mode == Mode.DISCHARGE
        assert decision.power == 500


class TestSelfConsumption:
    def test_self_consumption_during_peak(self):
        """Peak hours with self_consumption enabled -> SELF_CONSUMPTION mode."""
        state = make_state(grid_power=500, battery_soc=60, hour=14)
        decision = regulate(state, 0, SELF_CONSUMPTION_CONFIG)
        assert decision.mode == Mode.SELF_CONSUMPTION
        assert decision.power == 0

    def test_self_consumption_off_peak_charge_takes_priority(self):
        """Off-peak 2-6am charging overrides self-consumption."""
        state = make_state(is_off_peak=True, hour=3, battery_soc=30, tempo_color="Bleu")
        decision = regulate(state, 0, SELF_CONSUMPTION_CONFIG)
        assert decision.mode == Mode.CHARGE_OFF_PEAK
        assert decision.power == -1500

    def test_self_consumption_off_peak_outside_charge_window_soc_above_target(self):
        """Off-peak outside 2-6am, SOC >= target -> hold (not self-consumption)."""
        state = make_state(
            is_off_peak=True,
            hour=22,
            battery_soc=50,
            grid_power=-500,
            solar_production=600,
        )
        decision = regulate(state, 0, SELF_CONSUMPTION_CONFIG)
        assert decision.mode == Mode.AUTO
        assert decision.power == 0
        assert "hold" in decision.reason.lower()

    def test_self_consumption_off_peak_outside_charge_window_soc_below_target(self):
        """Off-peak outside 2-6am, SOC < target -> self-consumption (let it charge)."""
        state = make_state(
            is_off_peak=True,
            hour=22,
            battery_soc=20,
            grid_power=0,
            tempo_color="Rouge",  # target_soc = max(100 - 5*2, 60) = 90
        )
        decision = regulate(state, 0, SELF_CONSUMPTION_CONFIG)
        assert decision.mode == Mode.SELF_CONSUMPTION
        assert decision.power == 0

    def test_self_consumption_disabled_uses_feedback(self):
        """With self_consumption=False, normal feedback loop is used."""
        state = make_state(grid_power=500, battery_soc=80, hour=19, solar_remaining_kwh=0.0)
        decision = regulate(state, 0, DEFAULT_CONFIG)
        assert decision.mode == Mode.DISCHARGE
        assert decision.power == 500

    def test_genuine_surplus_during_discharge(self):
        """Solar surplus during discharge -> feedback naturally charges.

        Grid exporting 800W, battery discharging 200W.
        target = 200 + (-800) = -600 -> charge.
        """
        state = make_state(
            grid_power=-800,
            solar_production=2000,
            battery_soc=50,
            is_off_peak=False,
            hour=12,
            minute=0,
        )
        decision = regulate(state, 200, DEFAULT_CONFIG)
        assert decision.mode == Mode.CHARGE_SURPLUS
        assert decision.power == -600
