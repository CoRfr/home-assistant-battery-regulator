# Battery Regulator — Home Assistant Custom Integration

A Home Assistant custom integration that regulates a home battery system based on solar production, grid power, electricity tariff periods (HC/HP), and optionally EDF Tempo color days.

Designed to be **manufacturer-agnostic** — the regulation logic is pure Python with no hardware dependencies. Battery control is abstracted behind a `BatteryController` interface, with a Marstek implementation included.

## Features

- **Solar surplus charging** — absorbs excess solar production into the battery
- **Off-peak (HC) grid charging** — charges from grid during cheap hours to a computed target SOC
- **Peak (HP) discharge** — discharges to cover household load during expensive hours
- **Dynamic target SOC** — adjusts based on solar forecast and EDF Tempo color (Rouge/Blanc/Bleu)
- **Dynamic reserve SOC** — preserves enough battery for essential loads until next off-peak period
- **15-second regulation cycle** (configurable) with automatic retry on command failure
- **UI config flow** — configure all sensors and parameters through the HA interface

## Regulation Rules (priority order)

| # | Condition | Action |
|---|-----------|--------|
| 1 | HC, 2am-6am, SOC < target | Charge at -1500W |
| 2 | Was HC charging, SOC >= target | Auto |
| 3 | Grid < -100W, solar > 100W, SOC < 95% | Charge surplus at `grid+bat+100` (clamped -100 to -2500W) |
| 4 | HP, SOC > reserve, grid > 20W or discharging | Discharge at `grid+bat-20` (clamped 0 to 2500W) |
| 5 | Was surplus charging, grid >= -50W | Auto |
| 6 | Was discharging, conditions gone | Auto |
| 7 | Was HC charging, HP started | Auto |

## Architecture

```
custom_components/battery_regulator/
├── __init__.py           # Entry setup
├── manifest.json
├── config_flow.py        # 2-step UI config (generic sensors, then battery-specific)
├── const.py              # Config keys, defaults, constants
├── coordinator.py        # DataUpdateCoordinator: read sensors → regulate → command
├── regulator.py          # Pure decision logic (no HA imports, fully testable)
├── controller.py         # BatteryController ABC
├── marstek_controller.py # Marstek implementation (via marstek_local_api)
├── sensor.py             # 5 sensor entities
├── strings.json
└── translations/
    ├── en.json
    └── fr.json
```

### Key design decisions

- **`regulator.py` has zero HA imports** — all decision logic is pure Python with dataclasses, making it trivially unit-testable
- **`BatteryController` abstraction** — support other battery manufacturers by implementing `set_passive_mode()` and `set_auto_mode()`
- **Retry with latest state** — on command failure, retries run in a background task and always use the most recent regulation decision

## Installation

### Manual

Copy `custom_components/battery_regulator/` to your Home Assistant `config/custom_components/` directory and restart.

### As a git submodule (for version-controlled HA configs)

```bash
git submodule add https://github.com/CoRfr/home-assistant-battery-regulator.git
```

Then symlink or copy `custom_components/battery_regulator/` into your HA config.

## Configuration

After installation and restart, go to **Settings > Integrations > Add Integration > Battery Regulator**.

### Step 1 — Sensors & parameters

| Field | Description |
|-------|-------------|
| Grid power sensor | Net grid power (W). Positive = import, negative = export. |
| Solar production sensor | Current solar production (W) |
| Battery SOC sensor | Battery state of charge (%) |
| Battery power sensor | Battery power (W, **absolute value** — the integration determines sign from current mode) |
| Off-peak hours sensor | Binary sensor: on = off-peak (HC), off = peak (HP) |
| Solar forecast today | Today's total solar forecast (kWh) |
| Solar forecast remaining | Remaining solar forecast for today (kWh) |
| EDF Tempo color sensor | *(Optional)* EDF Tempo color for next day. Without it, a simplified target SOC formula is used. |
| Battery capacity | Battery capacity in Wh (default: 5120) |
| Base household load | Average base load in W for reserve calculation (default: 400) |
| Update interval | Regulation cycle interval in seconds (default: 15) |

### Step 2 — Marstek

| Field | Description |
|-------|-------------|
| Marstek device ID | Device ID for `marstek_local_api` service calls |
| Auto mode button | Button entity to switch battery to auto mode |

## Exposed Entities

| Entity | Description |
|--------|-------------|
| `sensor.battery_regulator_target_soc` | Computed target SOC (%) |
| `sensor.battery_regulator_reserve_soc` | Computed reserve SOC (%) |
| `sensor.battery_regulator_mode` | Current mode: `auto`, `charge_surplus`, `charge_hc`, `discharge` |
| `sensor.battery_regulator_commanded_power` | Last commanded power (W) |
| `sensor.battery_regulator_battery_power` | Battery power with sign (W, negative = charging) |

## Target SOC — how much to charge overnight

**Target SOC** is the battery level the integration tries to reach during off-peak grid charging (2am-6am). It answers: *"How full should the battery be by morning, given tomorrow's expected solar production?"*

- On a sunny day, less overnight charging is needed — solar will fill the battery during the day
- On a cloudy day or an expensive EDF Tempo day (Rouge/Blanc), charge more overnight while electricity is cheap

| EDF Tempo color | Formula | Example (5 kWh forecast) |
|-----------------|---------|--------------------------|
| Rouge / Blanc | `max(100 - forecast * 2, 60)` | 90% |
| Bleu | `max(60 - forecast * 2.5, 20)` | 48% |
| No EDF Tempo sensor | `max(80 - forecast * 3, 20)` | 65% |

## Reserve SOC — how much to keep for the evening

**Reserve SOC** is the minimum battery level the integration won't discharge below during peak hours. It answers: *"How much battery do I need to keep so the house can run on battery until the next off-peak period, accounting for remaining solar?"*

- During off-peak (HC): fixed at 10% (no need to reserve — electricity is cheap)
- During peak (HP): computed dynamically based on hours remaining until off-peak, base household load, and remaining solar forecast

**Formula:** `max(round((hours_to_HC * base_load_w - solar_remaining_wh) / capacity_wh * 100), 10)`

**Example:** At 2pm with 400W base load, 8 hours to off-peak, 2 kWh solar remaining, 5.12 kWh battery:
- Energy needed: 8h * 400W = 3,200 Wh
- Minus remaining solar: 3,200 - 2,000 = 1,200 Wh from battery
- Reserve: 1,200 / 5,120 = **23%**

Late evening (e.g. 9pm, 1h to HC): reserve drops to 10% (minimum) since very little energy is needed.

## Tests

```bash
pip install -r tests/requirements-test.txt
pytest tests/ -v
```

Tests cover the pure regulation logic in `regulator.py` — no Home Assistant installation required.

## Adding a new battery manufacturer

Implement the `BatteryController` interface:

```python
from .controller import BatteryController

class MyBatteryController(BatteryController):
    async def set_passive_mode(self, power: int, duration: int) -> None:
        # power: negative = charge, positive = discharge
        # duration: seconds
        ...

    async def set_auto_mode(self) -> None:
        ...
```

Then add a config flow step for your battery's specific settings and wire it up in `__init__.py`.

## License

MIT
