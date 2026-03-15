"""Constants for the Battery Regulator integration."""

DOMAIN = "battery_regulator"

# Config keys — generic sensors
CONF_GRID_POWER_SENSOR = "grid_power_sensor"
CONF_SOLAR_PRODUCTION_SENSOR = "solar_production_sensor"
CONF_BATTERY_SOC_SENSOR = "battery_soc_sensor"
CONF_BATTERY_POWER_SENSOR = "battery_power_sensor"
CONF_HC_HP_SENSOR = "hc_hp_sensor"
CONF_SOLAR_FORECAST_SENSOR = "solar_forecast_sensor"
CONF_SOLAR_REMAINING_SENSOR = "solar_remaining_sensor"
CONF_TEMPO_COLOR_SENSOR = "tempo_color_sensor"

# Config keys — battery parameters
CONF_BATTERY_POWER_UNSIGNED = "battery_power_unsigned"
CONF_BATTERY_CAPACITY_WH = "battery_capacity_wh"
CONF_BASE_LOAD_W = "base_load_w"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_HC_CHARGE_RATE = "hc_charge_rate"
CONF_MAX_CHARGE_RATE = "max_charge_rate"
CONF_MAX_DISCHARGE_RATE = "max_discharge_rate"
CONF_SURPLUS_THRESHOLD = "surplus_threshold"
CONF_SURPLUS_SOC_MAX = "surplus_soc_max"
CONF_DISCHARGE_MIN_POWER = "discharge_min_power"
CONF_SELF_CONSUMPTION = "self_consumption"

# Config keys — Marstek-specific
CONF_MARSTEK_DEVICE_ID = "marstek_device_id"
CONF_MARSTEK_AUTO_MODE_BUTTON = "marstek_auto_mode_button"

# Defaults — battery parameters
DEFAULT_BATTERY_CAPACITY_WH = 5120
DEFAULT_BASE_LOAD_W = 400
DEFAULT_UPDATE_INTERVAL_SECONDS = 15
DEFAULT_HC_CHARGE_RATE = 1500
DEFAULT_MAX_CHARGE_RATE = 2500
DEFAULT_MAX_DISCHARGE_RATE = 2500
DEFAULT_SURPLUS_THRESHOLD = 100
DEFAULT_SURPLUS_SOC_MAX = 95
DEFAULT_DISCHARGE_MIN_POWER = 50

# Retry settings
RETRY_DELAY_SECONDS = 5
RETRY_MAX_ATTEMPTS = 3

# Command refresh: re-send even when nothing changed to keep battery
# controller alive (Marstek passive mode expires after its duration).
COMMAND_REFRESH_SECONDS = 300
