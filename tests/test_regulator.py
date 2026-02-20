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


def make_state(**overrides) -> State:
    defaults = dict(
        grid_power=0,
        solar_production=0,
        battery_soc=50,
        battery_power_abs=0,
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
        assert compute_target_soc("Bleu", 16.0) == 20  # clamped

    def test_bleu_mid_solar(self):
        assert compute_target_soc("Bleu", 8.0) == 40

    def test_no_tempo(self):
        # Simplified formula: max(80 - forecast*3, 20)
        assert compute_target_soc(None, 0.0) == 80
        assert compute_target_soc(None, 20.0) == 20  # clamped


# --- compute_reserve_soc ---


class TestComputeReserveSoc:
    def test_off_peak_always_10(self):
        assert compute_reserve_soc(True, 3, 0, 400, 5.0, 5120) == 10

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
        # 21:00, 1h to off-peak, round(1*400/5120*100) ~= 8% -> clamped to min 10
        reserve = compute_reserve_soc(False, 21, 0, 400, 0.0, 5120)
        assert reserve == 10

    def test_after_22_zero_hours(self):
        # 22:30 -> hours_to_off_peak = max(22 - 22.5, 0) = 0
        reserve = compute_reserve_soc(False, 22, 30, 400, 0.0, 5120)
        assert reserve == 10  # min


# --- regulate: off-peak charging ---


class TestRegulateOffPeakCharge:
    def test_off_peak_charge_starts(self):
        state = make_state(is_off_peak=True, hour=3, battery_soc=30, tempo_color="Bleu")
        decision = regulate(state, Mode.AUTO, DEFAULT_CONFIG)
        assert decision.mode == Mode.CHARGE_OFF_PEAK
        assert decision.power == -1500

    def test_off_peak_charge_not_before_2am(self):
        state = make_state(is_off_peak=True, hour=1, battery_soc=30, tempo_color="Bleu")
        decision = regulate(state, Mode.AUTO, DEFAULT_CONFIG)
        assert decision.mode != Mode.CHARGE_OFF_PEAK

    def test_off_peak_charge_not_after_6am(self):
        state = make_state(is_off_peak=True, hour=6, battery_soc=30, tempo_color="Bleu")
        decision = regulate(state, Mode.AUTO, DEFAULT_CONFIG)
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
        decision = regulate(state, Mode.CHARGE_OFF_PEAK, DEFAULT_CONFIG)
        assert decision.mode == Mode.AUTO

    def test_off_peak_charge_retries_when_below_target(self):
        state = make_state(is_off_peak=True, hour=4, battery_soc=40, tempo_color="Bleu")
        decision = regulate(state, Mode.CHARGE_OFF_PEAK, DEFAULT_CONFIG)
        assert decision.mode == Mode.CHARGE_OFF_PEAK
        assert decision.power == -1500

    def test_off_peak_charge_stops_when_peak_starts(self):
        state = make_state(is_off_peak=False, hour=7, battery_soc=40, tempo_color="Bleu")
        decision = regulate(state, Mode.CHARGE_OFF_PEAK, DEFAULT_CONFIG)
        assert decision.mode == Mode.AUTO


# --- regulate: surplus charging ---


class TestRegulateSurplusCharge:
    def test_surplus_charge_starts(self):
        state = make_state(
            grid_power=-500,
            solar_production=600,
            battery_soc=60,
            battery_power_abs=0,
        )
        decision = regulate(state, Mode.AUTO, DEFAULT_CONFIG)
        assert decision.mode == Mode.CHARGE_SURPLUS
        # power = grid + bat + 100 = -500 + 0 + 100 = -400, clamped to [-2500, -100]
        assert decision.power == -400

    def test_surplus_adjusts_with_existing_charge(self):
        state = make_state(
            grid_power=-200,
            solar_production=800,
            battery_soc=60,
            battery_power_abs=500,
        )
        # Currently charging, bat_signed = -500
        decision = regulate(state, Mode.CHARGE_SURPLUS, DEFAULT_CONFIG)
        assert decision.mode == Mode.CHARGE_SURPLUS
        # power = -200 + (-500) + 100 = -600
        assert decision.power == -600

    def test_surplus_stops_when_gone(self):
        state = make_state(
            grid_power=0,
            solar_production=300,
            battery_soc=60,
            battery_power_abs=200,
        )
        decision = regulate(state, Mode.CHARGE_SURPLUS, DEFAULT_CONFIG)
        assert decision.mode == Mode.AUTO

    def test_surplus_no_charge_at_95(self):
        state = make_state(
            grid_power=-500,
            solar_production=600,
            battery_soc=95,
        )
        decision = regulate(state, Mode.AUTO, DEFAULT_CONFIG)
        assert decision.mode != Mode.CHARGE_SURPLUS

    def test_surplus_power_clamped_min(self):
        # Barely surplus
        state = make_state(
            grid_power=-110,
            solar_production=200,
            battery_soc=50,
            battery_power_abs=0,
        )
        decision = regulate(state, Mode.AUTO, DEFAULT_CONFIG)
        assert decision.mode == Mode.CHARGE_SURPLUS
        # power = -110 + 0 + 100 = -10, but clamped to -100 min
        assert decision.power == -100

    def test_surplus_power_clamped_max(self):
        # Huge surplus
        state = make_state(
            grid_power=-3000,
            solar_production=4000,
            battery_soc=50,
            battery_power_abs=0,
        )
        decision = regulate(state, Mode.AUTO, DEFAULT_CONFIG)
        assert decision.mode == Mode.CHARGE_SURPLUS
        assert decision.power == -2500  # clamped


# --- regulate: peak discharge ---


class TestRegulatePeakDischarge:
    def test_discharge_starts(self):
        # At 19:00, reserve = round(3*400/5120*100) = 23%, so SOC=60 > 23
        state = make_state(
            grid_power=500,
            battery_soc=60,
            battery_power_abs=100,
            is_off_peak=False,
            hour=19,
            solar_remaining_kwh=0.0,
        )
        decision = regulate(state, Mode.AUTO, DEFAULT_CONFIG)
        assert decision.mode == Mode.DISCHARGE
        # power = 500 + 0 - 20 = 480
        assert decision.power == 480

    def test_discharge_adjusts_with_existing(self):
        # At 19:00, reserve = 23%, SOC=60 > 23
        state = make_state(
            grid_power=100,
            battery_soc=60,
            battery_power_abs=400,
            is_off_peak=False,
            hour=19,
            solar_remaining_kwh=0.0,
        )
        # Already discharging, bat_signed = +400
        decision = regulate(state, Mode.DISCHARGE, DEFAULT_CONFIG)
        assert decision.mode == Mode.DISCHARGE
        # power = 100 + 400 - 20 = 480
        assert decision.power == 480

    def test_discharge_stops_in_off_peak(self):
        state = make_state(
            grid_power=500,
            battery_soc=60,
            battery_power_abs=400,
            is_off_peak=True,
            hour=23,
        )
        decision = regulate(state, Mode.DISCHARGE, DEFAULT_CONFIG)
        assert decision.mode == Mode.AUTO

    def test_discharge_stops_at_reserve(self):
        state = make_state(
            grid_power=500,
            battery_soc=10,
            battery_power_abs=400,
            is_off_peak=False,
            hour=21,
            solar_remaining_kwh=0.0,
        )
        # reserve at 21:00 with 0 solar = max(round(1*400/5120*100), 10) = 10
        # SOC=10 <= reserve=10 -> stop
        decision = regulate(state, Mode.DISCHARGE, DEFAULT_CONFIG)
        assert decision.mode == Mode.AUTO

    def test_discharge_not_during_surplus_charge(self):
        state = make_state(
            grid_power=500,
            battery_soc=60,
            battery_power_abs=400,
            is_off_peak=False,
            hour=14,
        )
        decision = regulate(state, Mode.CHARGE_SURPLUS, DEFAULT_CONFIG)
        # Should stop surplus (grid >= -50), not start discharge
        assert decision.mode == Mode.AUTO

    def test_discharge_power_clamped(self):
        state = make_state(
            grid_power=3000,
            battery_soc=80,
            battery_power_abs=100,
            is_off_peak=False,
            hour=14,
            solar_remaining_kwh=0.0,
        )
        decision = regulate(state, Mode.AUTO, DEFAULT_CONFIG)
        assert decision.mode == Mode.DISCHARGE
        assert decision.power == 2500  # clamped

    def test_discharge_skipped_low_power(self):
        state = make_state(
            grid_power=30,
            battery_soc=60,
            battery_power_abs=60,
            is_off_peak=False,
            hour=14,
            solar_remaining_kwh=0.0,
        )
        decision = regulate(state, Mode.AUTO, DEFAULT_CONFIG)
        # power = 30 + 0 - 20 = 10, < 50 -> skip
        assert decision.mode != Mode.DISCHARGE


# --- regulate: priority / edge cases ---


class TestRegulatePriority:
    def test_off_peak_charge_overrides_surplus(self):
        """During off-peak 2-6am with low SOC, off-peak charge takes priority over surplus."""
        state = make_state(
            is_off_peak=True,
            hour=3,
            battery_soc=30,
            grid_power=-500,
            solar_production=600,
            tempo_color="Bleu",
        )
        decision = regulate(state, Mode.AUTO, DEFAULT_CONFIG)
        assert decision.mode == Mode.CHARGE_OFF_PEAK

    def test_no_change_stays_auto(self):
        """When nothing triggers, stay in auto."""
        state = make_state(
            grid_power=5,
            solar_production=0,
            battery_soc=50,
            battery_power_abs=0,
            is_off_peak=False,
            hour=14,
        )
        decision = regulate(state, Mode.AUTO, DEFAULT_CONFIG)
        assert decision.mode == Mode.AUTO

    def test_live_snapshot_2026_02_20_1400(self):
        """Snapshot of live sensor state at 2026-02-20 14:00 (Europe/Paris).

        Sensors:
          grid_power:          -443 W (exporting)
          solar_production:     559 W
          battery_soc:           52 %
          battery_power_abs:      8 W (Sonoff — barely charging)
          is_off_peak:         False (peak — normal at 14:00)
          hour/minute:         14:00
          solar_forecast:      9.124 kWh
          solar_remaining:     3.668 kWh
          tempo_color:         Bleu

        Old YAML had commanded_mode=charge, power=-338 (surplus charging).
        The regulator should continue surplus charging because
        grid < -100 and production > 100 and SOC < 95.

        Expected power = grid + bat_signed + 100
          bat_signed for CHARGE_SURPLUS with abs=8 → -8
          = -443 + (-8) + 100 = -351, clamped [-2500, -100] → -351
        """
        state = State(
            grid_power=-443,
            solar_production=559,
            battery_soc=52,
            battery_power_abs=8,
            is_off_peak=False,
            hour=14,
            minute=0,
            solar_forecast_kwh=9.124,
            solar_remaining_kwh=3.668,
            tempo_color="Bleu",
        )

        # Already surplus charging (as old YAML was doing)
        decision = regulate(state, Mode.CHARGE_SURPLUS, DEFAULT_CONFIG)
        assert decision.mode == Mode.CHARGE_SURPLUS
        assert decision.power == -351

        # Starting from AUTO should also trigger surplus
        decision_fresh = regulate(state, Mode.AUTO, DEFAULT_CONFIG)
        assert decision_fresh.mode == Mode.CHARGE_SURPLUS
        # From AUTO, bat_signed=0: -443 + 0 + 100 = -343
        assert decision_fresh.power == -343

        # Verify target_soc: Bleu, 9.124 kWh → max(60 - 9.124*2.5, 20) = max(37, 20) = 37
        assert compute_target_soc("Bleu", 9.124) == 37

        # Verify reserve_soc: peak, 14:00, 3.668 kWh remaining
        # hours_to_off_peak = max(22 - 14, 0) = 8
        # energy_needed = 8 * 400 = 3200
        # solar_remaining_wh = 3668
        # from_battery = max(3200 - 3668, 0) = 0
        # reserve = max(round(0 / 5120 * 100), 10) = 10
        reserve = compute_reserve_soc(False, 14, 0, 400, 3.668, 5120)
        assert reserve == 10

    def test_surplus_during_off_peak_outside_charge_window(self):
        """Off-peak but outside 2-6am window — surplus can charge."""
        state = make_state(
            is_off_peak=True,
            hour=22,
            battery_soc=50,
            grid_power=-500,
            solar_production=600,
        )
        decision = regulate(state, Mode.AUTO, DEFAULT_CONFIG)
        assert decision.mode == Mode.CHARGE_SURPLUS
