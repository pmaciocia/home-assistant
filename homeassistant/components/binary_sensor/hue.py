"""
This component provides binary sensor support for the Philips Hue system.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/sensor.hue/
"""
import asyncio
from datetime import timedelta
import logging
import async_timeout

from aiohue.sensors import (TYPE_CLIP_GENERICFLAG, TYPE_CLIP_OPENCLOSE, TYPE_CLIP_PRESENCE,
                            TYPE_DAYLIGHT, TYPE_ZLL_PRESENCE)

import homeassistant.components.hue as hue
from homeassistant.components.hue.const import (ICON_DAY, ICON_NIGHT)
from homeassistant.components.sensor.hue import HueSensor
from homeassistant.const import (ATTR_BATTERY_LEVEL, STATE_OFF, STATE_ON)
from homeassistant.components.binary_sensor import BinarySensorDevice

DEPENDENCIES = ['hue']
SCAN_INTERVAL = timedelta(seconds=1)

ALL_BINARY_SENSORS = [TYPE_CLIP_GENERICFLAG, TYPE_CLIP_OPENCLOSE, TYPE_CLIP_PRESENCE,
                      TYPE_DAYLIGHT, TYPE_ZLL_PRESENCE]
HUE_BINARY_SENSORS = [TYPE_DAYLIGHT, TYPE_ZLL_PRESENCE]

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(hass, config, async_add_devices,
                               discovery_info=None):
    """Old way of setting up Hue.

    Can only be called when a user accidentally mentions hue platform in their
    config. But even in that case it would have been ignored.
    """
    pass


async def async_setup_entry(hass, config_entry, async_add_devices):
    """Set up the Hue sensors from a config entry."""
    bridge = hass.data[hue.DOMAIN][config_entry.data['host']]
    cur_sensors = {}

    # Hue updates all devices via a single API call.
    #
    # If we call a service to update 2 devices, we only want the API to be
    # called once.
    #
    # The throttle decorator will return right away if a call is currently
    # in progress. This means that if we are updating 2 devices, the first one
    # is in the update method, the second one will skip it and assume the
    # update went through and updates it's data, not good!
    #
    # The current mechanism will make sure that all devices will wait till
    # the update call is done before writing their data to the state machine.
    #
    # An alternative approach would be to disable automatic polling by Home
    # Assistant and take control ourselves. This works great for polling as now
    # we trigger from 1 time update an update to all entities. However it gets
    # tricky from inside async_turn_on and async_turn_off.
    #
    # If automatic polling is enabled, Home Assistant will call the entity
    # update method after it is done calling all the services. This means that
    # when we update, we know all commands have been processed. If we trigger
    # the update from inside async_turn_on, the update will not capture the
    # changes to the second entity until the next polling update because the
    # throttle decorator will prevent the call.

    progress = None
    sensor_progress = set()

    async def request_update(object_id):
        """Request an update.

        We will only make 1 request to the server for updating at a time. If a
        request is in progress, we will join the request that is in progress.

        This approach is possible because should_poll=True. That means that
        Home Assistant will ask sensors for updates during a polling cycle or
        after it has called a service.

        We keep track of the sensors that are waiting for the request to finish.
        When new data comes in, we'll trigger an update for all non-waiting
        sensors. This covers the case where a service is called to modify 2
        sensors but in the meanwhile some other sensor has changed too.
        """
        nonlocal progress

        progress_set = sensor_progress
        progress_set.add(object_id)

        if progress is not None:
            return await progress

        progress = asyncio.ensure_future(update_bridge())
        result = await progress
        progress = None
        sensor_progress.clear()
        return result

    async def update_bridge():
        """Update the values of the bridge.

        Will update sensors from the bridge.
        """
        tasks = []
        tasks.append(async_update_items(
            hass, bridge, async_add_devices, request_update,
            cur_sensors, sensor_progress
        ))

        await asyncio.wait(tasks)

    await update_bridge()


async def async_update_items(hass, bridge, async_add_devices,
                             request_bridge_update, current,
                             progress_waiting):
    """Update sensors from the bridge."""
    import aiohue
    #allow_clip_sensors = bridge.allow_clip_sensors
    allow_clip_sensors = True

    api = bridge.api.sensors

    try:
        with async_timeout.timeout(4):
            await api.update()
    except (asyncio.TimeoutError, aiohue.AiohueException):
        if not bridge.available:
            return

        _LOGGER.error('Unable to reach bridge %s', bridge.host)
        bridge.available = False

        for sensor_id, sensor in current.items():
            if sensor_id not in progress_waiting:
                sensor.async_schedule_update_ha_state()

        return

    if not bridge.available:
        _LOGGER.info('Reconnected to bridge %s', bridge.host)
        bridge.available = True

    new_sensors = []

    if allow_clip_sensors:
        allowed_binary_sensor_types = ALL_BINARY_SENSORS
    else:
        allowed_binary_sensor_types = HUE_BINARY_SENSORS

    for item_id in api:
        binary_sensor = api[item_id]
        if binary_sensor.type in allowed_binary_sensor_types:
            if item_id not in current:
                current[item_id] = create_binary_sensor(
                    binary_sensor, request_bridge_update, bridge)

                new_sensors.append(current[item_id])
                _LOGGER.info('Added new Hue binary sensor: %s (Type: %s)',
                             binary_sensor.name, binary_sensor.type)
            elif item_id not in progress_waiting:
                current[item_id].async_schedule_update_ha_state()

    if new_sensors:
        async_add_devices(new_sensors)


class HueBinarySensor(HueSensor):
    """Base class representing a Hue Binary Sensor.
    Contains properties and methods common to all Hue binary sensors."""

    @property
    def is_on(self):
        """Return true if the binary sensor is on."""
        return None

    @property
    def state(self):
        """Return the state of the Hue binary sensor."""
        return STATE_ON if self.is_on else STATE_OFF


class CLIPGenericFlag(HueBinarySensor):

    @property
    def is_on(self):
        """Return true if the CLIP binary sensor is on."""
        return self.sensor.flag


class CLIPOpenClose(HueBinarySensor):

    @property
    def is_on(self):
        """Return true if the CLIP binary sensor is on."""
        return self.sensor.open

    @property
    def device_class(self):
        """Return the device class of the CLIP binary sensor."""
        return 'opening'


class CLIPPresence(HueBinarySensor):

    @property
    def is_on(self):
        """Return true if the CLIP binary sensor is on."""
        return self.sensor.presence

    @property
    def device_class(self):
        """Return the device class of the CLIP binary sensor."""
        return 'presence'


class Daylight(HueBinarySensor):
    """Class representing the Hue Daylight sensor."""

    @property
    def available(self):
        """The daylight sensor is always available."""
        return True

    @property
    def unique_id(self):
        """Generate a unique id for the Daylight sensor, based on the
        unique bridge id of the bridge and the suffix 'daylight'"""
        return self.bridge.api.config.bridgeid + '_daylight'

    @property
    def is_on(self):
        """Return true if the Hue Daylight sensor is on."""
        return self.sensor.daylight

    @property
    def icon(self):
        """Return an icon for the Hue Daylight sensor based on state."""
        if self.is_on:
            return ICON_DAY
        else:
            return ICON_NIGHT

    @property
    def device_state_attributes(self):
        """Return the device state attributes."""
        attributes = {}
        return attributes



class ZLLPresence(HueBinarySensor):
    """Class representing a Hue Motion Sensor."""

    @property
    def is_on(self):
        """Return true if the Hue Motion Sensor is on."""
        return self.sensor.presence

    @property
    def device_class(self):
        """Return the device class of the Hue Motion Sensor."""
        return 'motion'


def create_binary_sensor(sensor, request_bridge_update, bridge):
    binary_sensor_type = sensor.type
    if binary_sensor_type == TYPE_CLIP_GENERICFLAG:
        return CLIPGenericFlag(sensor, request_bridge_update, bridge)
    elif binary_sensor_type == TYPE_CLIP_OPENCLOSE:
        return CLIPOpenClose(sensor, request_bridge_update, bridge)
    elif binary_sensor_type == TYPE_CLIP_PRESENCE:
        return CLIPPresence(sensor, request_bridge_update, bridge)
    elif binary_sensor_type == TYPE_DAYLIGHT:
        return Daylight(sensor, request_bridge_update, bridge)
    elif binary_sensor_type == TYPE_ZLL_PRESENCE:
        return ZLLPresence(sensor, request_bridge_update, bridge)
