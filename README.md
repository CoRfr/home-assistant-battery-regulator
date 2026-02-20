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

## How it works

Every 15 seconds (configurable), the regulator reads all sensors, decides what the battery should do, and sends a command. Rules are evaluated in priority order — the first matching rule wins.

### 1. Off-peak grid charging (2am–6am)

During off-peak hours between 2am and 6am, if the battery is below the [target SOC](#target-soc--how-much-to-charge-overnight), charge from the grid at the configured off-peak charge rate (default: 1500W). This tops up the battery with cheap electricity before the day starts. The command is re-sent every cycle as a retry mechanism until the target is reached.

**Stops** when the battery reaches the target SOC, or when peak hours begin.

### 2. Solar surplus charging

When the house is exporting to the grid (above the surplus threshold, default 100W) and solar panels are producing (above the same threshold), redirect that surplus into the battery to maximize self-consumption. The charge power is continuously adjusted to absorb exactly the surplus:

```
charge_power = grid_power + current_battery_power + 100W margin
```

This targets roughly 100W of grid export (to avoid accidentally importing). Power is clamped between the surplus threshold and the max charge rate.

**Stops** when the surplus disappears (grid export drops below 50W), or when the battery reaches the max surplus SOC (default: 95%).

### 3. Peak hour discharge

During peak hours, if the house is importing from the grid and the battery is above the [reserve SOC](#reserve-soc--how-much-to-keep-for-the-evening), discharge the battery to cover household consumption. The discharge power is adjusted to target ~20W of grid import (enough to avoid exporting):

```
discharge_power = grid_power + current_battery_power - 20W offset
```

Power is clamped between 0W and the max discharge rate. Discharge is skipped if the computed power is below the min discharge power (default: 50W — not worth the wear).

**Stops** when off-peak hours begin, or when the battery drops to the reserve SOC.

### Priority

Rules are evaluated in this order, first match wins:

1. **Off-peak charge** (cheap electricity) — highest priority
2. **Surplus charge** (free solar) — takes precedence over discharge
3. **Peak discharge** (avoid expensive imports) — only when not charging
4. **Stop rules** — return to auto mode when conditions no longer hold

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
| Off-peak charge rate | Charge power during off-peak hours in W (default: 1500) |
| Max charge rate | Maximum charge power in W (default: 2500) |
| Max discharge rate | Maximum discharge power in W (default: 2500) |
| Surplus threshold | Grid export threshold to start surplus charging in W (default: 100) |
| Max SOC for surplus | Stop surplus charging above this SOC in % (default: 95) |
| Min discharge power | Minimum discharge power worth sending in W (default: 50) |
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

## Development

```bash
poetry install
poetry run pre-commit install
```

Pre-commit hooks run ruff (lint + format) and pytest on every commit.

## Tests

```bash
poetry run pytest tests/ -v
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
