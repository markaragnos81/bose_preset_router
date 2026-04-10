DOMAIN = "bose_preset_router"

CONF_NOTIFY_ON_PRESS = "notify_on_press"
CONF_DEBUG_LOGGING = "debug_logging"
CONF_DEBOUNCE_SECONDS = "debounce_seconds"
CONF_PLAYBACK_VERIFY_ATTEMPTS = "playback_verify_attempts"
CONF_PLAYBACK_VERIFY_DELAY_SECONDS = "playback_verify_delay_seconds"
CONF_STRICT_BOSE_CONFIRMATION = "strict_bose_confirmation"
CONF_TOLERANT_BOSE_CONFIRMATION = "tolerant_bose_confirmation"

CONF_NAME = "name"
CONF_BOSE_IP = "bose_ip"
CONF_MA_PLAYER = "ma_player"
CONF_DEFAULT_VOLUME = "default_volume"

ATTR_DEVICE = "device"
ATTR_PRESET = "preset"

SERVICE_TRIGGER_PRESET = "trigger_preset"

DEFAULT_NOTIFY_ON_PRESS = False
DEFAULT_DEBUG_LOGGING = False
DEFAULT_DEBOUNCE_SECONDS = 2.0
DEFAULT_PLAYBACK_VERIFY_ATTEMPTS = 3
DEFAULT_PLAYBACK_VERIFY_DELAY_SECONDS = 1.5
DEFAULT_STRICT_BOSE_CONFIRMATION = True
DEFAULT_TOLERANT_BOSE_CONFIRMATION = False

WS_PORT = 8080
SUBENTRY_TYPE_DEVICE = "device"
PRESET_IDS = (1, 2, 3, 4, 5, 6)


def preset_url_key(preset: int) -> str:
    return f"preset_{preset}"


def preset_enabled_key(preset: int) -> str:
    return f"preset_{preset}_enabled"


def preset_volume_key(preset: int) -> str:
    return f"preset_{preset}_volume"
