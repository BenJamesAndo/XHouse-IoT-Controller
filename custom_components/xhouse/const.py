from logging import getLogger

DOMAIN = "xhouse"
LOGGER = getLogger(__package__)

CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_REFRESH_INTERVAL = "refresh_interval"
CONF_DEBUG_MODE = "debug_mode"

DEFAULT_REFRESH_INTERVAL = 30

API_BASE_URL = "https://iemp.giigleiot.net/xhouseAppEncapsulation"
HMAC_SECRET_KEY = "juge2020@giigleiot"
SAAS_CODE = "JUJIANG"
PLATFORM_CODE = "giigle"
APP_TYPE = "android"

KNOWN_MODELS = ["XH-SGC01", "EGA"]

NON_CONTROL_PROPERTIES = {
    "VoiceControl",
    "bleCode",
    "wifiName",
    "status",
    "menuCode",
    "boardVersion",
    "updateStatusTime",
}

PLATFORMS = ["cover", "switch", "button"]
