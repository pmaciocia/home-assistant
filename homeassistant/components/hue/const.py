"""Constants for the Hue component."""
import logging

LOGGER = logging.getLogger('homeassistant.components.hue')
DOMAIN = "hue"
API_NUPNP = 'https://www.meethue.com/api/nupnp'

ATTR_DARK = 'dark'
ATTR_DAYLIGHT = 'daylight'

ICON_REMOTE = 'mdi:remote'
ICON_DAY = 'mdi:weather-sunny'
ICON_NIGHT = 'mdi:weather-night'

UOM_HUMIDITY = '%'
UOM_ILLUMINANCE = 'lx'