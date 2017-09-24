"""Module to handle messages from Home Assistant cloud."""
import asyncio
import json
import logging

from homeassistant.util.decorator import Registry
from homeassistant.components.alexa import smart_home
from .const import ALEXA_PUBLISH_TOPIC

HANDLERS = Registry()
_LOGGER = logging.getLogger(__name__)


@asyncio.coroutine
def async_handle_message(hass, cloud, handler_name, payload):
    """Handle incoming IoT message."""
    handler = HANDLERS.get(handler_name)

    if handler is None:
        _LOGGER.warning('Unable to handle message for %s', handler_name)
        return

    yield from handler(hass, cloud, payload)


@HANDLERS.register('alexa')
@asyncio.coroutine
def async_handle_alexa(hass, cloud, payload):
    """Handle an incoming IoT message for Alexa."""
    message = json.loads(payload)
    response = yield from smart_home.async_handle_message(hass, message)
    message_id = message[smart_home.ATTR_HEADER][smart_home.ATTR_MESSAGE_ID]
    yield from hass.async_add_job(
        cloud.publish, ALEXA_PUBLISH_TOPIC.format(message_id),
        json.dumps(response))
