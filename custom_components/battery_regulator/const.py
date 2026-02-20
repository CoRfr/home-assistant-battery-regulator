"""Constants for the Battery Regulator integration."""

DOMAIN = "battery_regulator"

# Config keys — generic
CONF_GRID_POWER_SENSOR = "grid_power_sensor"
CONF_SOLAR_PRODUCTION_SENSOR = "solar_production_sensor"
CONF_BATTERY_SOC_SENSOR = "battery_soc_sensor"
CONF_BATTERY_POWER_SENSOR = "battery_power_sensor"
CONF_HC_HP_SENSOR = "hc_hp_sensor"
CONF_SOLAR_FORECAST_SENSOR = "solar_forecast_sensor"
CONF_SOLAR_REMAINING_SENSOR = "solar_remaining_sensor"
CONF_TEMPO_COLOR_SENSOR = "tempo_color_sensor"
CONF_BATTERY_CAPACITY_WH = "battery_capacity_wh"
CONF_BASE_LOAD_W = "base_load_w"
CONF_UPDATE_INTERVAL = "update_interval"

# Config keys — Marstek-specific
CONF_MARSTEK_DEVICE_ID = "marstek_device_id"
CONF_MARSTEK_AUTO_MODE_BUTTON = "marstek_auto_mode_button"

# Defaults
DEFAULT_BATTERY_CAPACITY_WH = 5120
DEFAULT_BASE_LOAD_W = 400

# Regulation constants
CHARGE_HC_POWER = -1500
HC_CHARGE_START_HOUR = 2
HC_CHARGE_END_HOUR = 6
SURPLUS_GRID_THRESHOLD = -100
SURPLUS_PRODUCTION_MIN = 100
SURPLUS_SOC_MAX = 95
SURPLUS_STOP_GRID_THRESHOLD = -50
DISCHARGE_GRID_OFFSET = 20
DISCHARGE_MIN_POWER = 50
CHARGE_SURPLUS_OFFSET = 100
CHARGE_POWER_MIN = -2500
CHARGE_POWER_MAX = -100
DISCHARGE_POWER_MIN = 0
DISCHARGE_POWER_MAX = 2500
HC_RESERVE_SOC = 10
HP_START_HOUR = 22

# Update interval
DEFAULT_UPDATE_INTERVAL_SECONDS = 15

# Retry settings
RETRY_DELAY_SECONDS = 5
RETRY_MAX_ATTEMPTS = 3
