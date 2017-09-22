"""Component to integrate the Home Assistant cloud."""
import asyncio
import json
import logging
import os

import voluptuous as vol

from . import http_api, iot
from .const import (
    CONFIG_DIR, DOMAIN, SERVERS, PUBLISH_TOPIC_FORMAT, SUBSCRIBE_TOPIC_FORMAT,
    IOT_KEEP_ALIVE)
from homeassistant.const import EVENT_HOMEASSISTANT_STOP


REQUIREMENTS = ['warrant==0.2.0', 'AWSIoTPythonSDK==1.2.0']
DEPENDENCIES = ['http']
CONF_MODE = 'mode'
CONF_COGNITO_CLIENT_ID = 'cognito_client_id'
CONF_USER_POOL_ID = 'user_pool_id'
CONF_REGION = 'region'
CONF_API_BASE = 'api_base'
CONF_IOT_ENDPOINT = 'iot_endpoint'
MODE_DEV = 'development'
DEFAULT_MODE = MODE_DEV
_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Optional(CONF_MODE, default=DEFAULT_MODE):
            vol.In([MODE_DEV] + list(SERVERS)),
        # Change to optional when we include real servers
        vol.Required(CONF_COGNITO_CLIENT_ID): str,
        vol.Required(CONF_USER_POOL_ID): str,
        vol.Required(CONF_REGION): str,
        vol.Required(CONF_API_BASE): str,
        vol.Required(CONF_IOT_ENDPOINT): str,
    }),
}, extra=vol.ALLOW_EXTRA)


@asyncio.coroutine
def async_setup(hass, config):
    """Initialize the Home Assistant cloud."""
    if DOMAIN in config:
        kwargs = config[DOMAIN]
    else:
        kwargs = {CONF_MODE: DEFAULT_MODE}

    cloud = hass.data[DOMAIN] = Cloud(hass, **kwargs)
    yield from hass.async_add_job(cloud.initialize)
    yield from http_api.async_setup(hass)
    return True


class Cloud:
    """Hold the state of the cloud connection."""

    def __init__(self, hass, mode, cognito_client_id=None, user_pool_id=None,
                 region=None, api_base=None, iot_endpoint=None):
        """Create an instance of Cloud."""
        self.hass = hass
        self.mode = mode
        self.email = None
        self.thing_name = None
        self.client = None

        if mode == MODE_DEV:
            self.cognito_client_id = cognito_client_id
            self.user_pool_id = user_pool_id
            self.region = region
            self.api_base = api_base
            self.iot_endpoint = iot_endpoint

        else:
            info = SERVERS[mode]

            self.cognito_client_id = info['cognito_client_id']
            self.user_pool_id = info['user_pool_id']
            self.region = info['region']
            self.api_base = info['api_base']
            self.iot_endpoint = info['iot_endpoint']

    @property
    def is_connected(self):
        """Return if we are connected."""
        return self.client is not None

    @property
    def certificate_pem_path(self):
        """Get path to certificate pem."""
        return self.path('{}_iot_certificate.pem'.format(self.mode))

    @property
    def secret_key_path(self):
        """Get path to public key."""
        return self.path('{}_iot_secret.key'.format(self.mode))

    @property
    def user_info_path(self):
        """Get path to the stored auth."""
        return self.path('{}_auth.json'.format(self.mode))

    def initialize(self):
        """Initialize and load cloud info."""
        # Ensure config dir exists
        path = self.hass.config.path(CONFIG_DIR)
        if not os.path.isdir(path):
            os.mkdir(path)

        self.hass.bus.listen_once(EVENT_HOMEASSISTANT_STOP,
                                  self._handle_hass_stop)

        user_info = self.user_info_path
        if os.path.isfile(user_info):
            with open(user_info, 'rt') as file:
                info = json.loads(file.read())
            self.email = info['email']
            self.thing_name = info['thing_name']
            self.connect()

    def connect(self):
        """Connect to the IoT broker."""
        from AWSIoTPythonSDK.exception.operationError import operationError
        from AWSIoTPythonSDK.exception.operationTimeoutException import \
            operationTimeoutException

        assert self.client is None, 'Cloud already connected'

        client = _client_factory(self)

        def message_callback(mqtt_client, userdata, msg):
            """Handle IoT message."""
            handler = msg.topic.split('/', 2)[2]

            self.hass.add_job(iot.async_handle_message, self.hass, self,
                              handler, msg.payload)

        try:
            if not client.connect(keepAliveIntervalSecond=IOT_KEEP_ALIVE):
                return

            client.subscribe(SUBSCRIBE_TOPIC_FORMAT.format(self.thing_name), 1,
                             message_callback)
            self.client = client
        except (OSError, operationError, operationTimeoutException):
            # SSL Error, connect error, timeout.
            pass

    def publish(self, topic, payload):
        """Publish a message to the cloud."""
        self.client.publish(
            PUBLISH_TOPIC_FORMAT.format(self.thing_name, topic), payload, 1)

    def path(self, *parts):
        """Get config path inside cloud dir."""
        return self.hass.config.path(CONFIG_DIR, *parts)

    def logout(self):
        """Close connection and remove all credentials."""
        self.client.disconnect()
        self.client = None
        self.email = None
        self.thing_name = None
        for file in (self.certificate_pem_path, self.secret_key_path,
                     self.user_info_path):
            try:
                os.remove(file)
            except FileNotFoundError:
                pass

    def _handle_hass_stop(self, event):
        """Handle Home Assistan shutting down."""
        if self.client is not None:
            self.client.disconnect()


def _client_factory(cloud):
    """Create IoT client."""
    from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
    root_ca = os.path.join(os.path.dirname(__file__), 'aws_iot_root_cert.pem')

    client = AWSIoTMQTTClient(cloud.thing_name)
    client.configureEndpoint(cloud.iot_endpoint, 8883)
    client.configureCredentials(root_ca, cloud.secret_key_path,
                                cloud.certificate_pem_path)

    # client.configureOfflinePublishQueueing(-1)  # Infinite offline Publish queueing
    # client.configureDrainingFrequency(2)  # Draining: 2 Hz
    # client.configureConnectDisconnectTimeout(10)  # 10 sec
    # client.configureMQTTOperationTimeout(5)  # 5 sec
    return client
