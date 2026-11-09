"""Constants for the Ocular EV Charger (cloud) integration."""

DOMAIN = "ocular"

# Taken from the Ocular Android app v1.7.9 (com.iocharger.family.ocular)
BASE_URL = "https://ocpp.ocularcharging.com.au:9110/"
LANG = "en"

CONF_PASSWORD_HASH = "password_hash"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 30  # seconds, live status
HISTORY_INTERVAL = 900  # seconds, charging history
HISTORY_DAYS = 30

# Per-session charge modes (TransactionSettingVO.eco)
SESSION_MODES = ["Fast", "Eco", "EcoPlus"]
# Solar / gateway modes (switchEcoMode) - app shows Fast, Solar Assist (PV), Solar (PV_plus)
SOLAR_MODES = {"Fast": "Fast", "PV": "Solar Assist", "PV_plus": "Solar"}

MIN_CURRENT = 6
DEFAULT_MAX_CURRENT = 32
NOMINAL_VOLTAGE = 230
