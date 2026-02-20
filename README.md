# Battery Regulator — Home Assistant Custom Integration

A Home Assistant custom integration that regulates a home battery system based on solar production, grid power, electricity tariff periods (HC/HP), and optionally Tempo color days.

Designed to be **manufacturer-agnostic** — the regulation logic is pure Python with no hardware dependencies. Battery control is abstracted behind a `BatteryController` interface, with a Marstek implementation included.

## Features

- **Solar surplus charging** — absorbs excess solar production into the battery
- **Off-peak (HC) grid charging** — charges from grid during cheap hours to a computed target SOC
- **Peak (HP) discharge** — discharges to cover household load during expensive hours
- **Dynamic target SOC** — adjusts based on solar forecast and Tempo color (Rouge/Blanc/Bleu)
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
| Tempo color sensor | *(Optional)* Tempo color for next day. Without it, a simplified target SOC formula is used. |
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

## Target SOC Formula

| Tempo color | Formula |
|-------------|---------|
| Rouge / Blanc | `max(100 - forecast_kwh * 2, 60)` |
| Bleu | `max(60 - forecast_kwh * 2.5, 20)` |
| No Tempo sensor | `max(80 - forecast_kwh * 3, 20)` |

## Reserve SOC Formula

- **During HC:** 10% (fixed minimum)
- **During HP:** `max(round((hours_to_HC * base_load_w - solar_remaining_wh) / capacity_wh * 100), 10)`

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
