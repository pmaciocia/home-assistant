"""Package to offer tools to authenticate with the cloud."""
import json
import logging
from urllib.parse import urljoin

import requests

_LOGGER = logging.getLogger(__name__)


class CloudError(Exception):
    """Base class for cloud related errors."""


class Unauthenticated(CloudError):
    """Raised when authentication failed."""


class UserNotFound(CloudError):
    """Raised when a user is not found."""


class UserNotConfirmed(CloudError):
    """Raised when a user has not confirmed email yet."""


class ExpiredCode(CloudError):
    """Raised when an expired code is encoutered."""


class InvalidCode(CloudError):
    """Raised when an invalid code is submitted."""


class PasswordChangeRequired(CloudError):
    """Raised when a password change is required."""

    def __init__(self, message='Password change required.'):
        """Initialize a password change required error."""
        super().__init__(message)


class UnknownError(CloudError):
    """Raised when an unknown error occurrs."""


AWS_EXCEPTIONS = {
    'UserNotFoundException': UserNotFound,
    'NotAuthorizedException': Unauthenticated,
    'ExpiredCodeException': ExpiredCode,
    'UserNotConfirmedException': UserNotConfirmed,
    'PasswordResetRequiredException': PasswordChangeRequired,
    'CodeMismatchException': InvalidCode,
}


def _map_aws_exception(err):
    """Map AWS exception to our exceptions."""
    ex = AWS_EXCEPTIONS.get(err.response['Error']['Code'], UnknownError)
    return ex(err.response['Error']['Message'])


def register(cloud, email, password):
    """Register a new account."""
    from botocore.exceptions import ClientError

    cognito = _cognito(cloud, username=email)
    try:
        cognito.register(email, password)
    except ClientError as err:
        raise _map_aws_exception(err)


def confirm_register(cloud, confirmation_code, email):
    """Confirm confirmation code after registration."""
    from botocore.exceptions import ClientError

    cognito = _cognito(cloud, username=email)
    try:
        cognito.confirm_sign_up(confirmation_code, email)
    except ClientError as err:
        raise _map_aws_exception(err)


def forgot_password(cloud, email):
    """Initiate forgotten password flow."""
    from botocore.exceptions import ClientError

    cognito = _cognito(cloud, username=email)
    try:
        cognito.initiate_forgot_password()
    except ClientError as err:
        raise _map_aws_exception(err)


def confirm_forgot_password(cloud, confirmation_code, email, new_password):
    """Confirm forgotten password code and change password."""
    from botocore.exceptions import ClientError

    cognito = _cognito(cloud, username=email)
    try:
        cognito.confirm_forgot_password(confirmation_code, new_password)
    except ClientError as err:
        raise _map_aws_exception(err)


def login(cloud, email, password):
    """Log user in and fetch certificate."""
    cognito = _authenticate(cloud, email, password)
    id_token = cognito.id_token
    cert = _retrieve_iot_certificate(cloud, id_token)
    cloud.email = email
    cloud.thing_name = cert['thing_name']
    _write_info(cloud, email, cert)
    cognito.logout()


def _authenticate(cloud, email, password):
    """Log in and return an authenticated Cognito instance."""
    from botocore.exceptions import ClientError
    from warrant.exceptions import ForceChangePasswordException

    cognito = _cognito(cloud, username=email)

    try:
        cognito.authenticate(password=password)
        return cognito

    except ForceChangePasswordException as err:
        raise PasswordChangeRequired

    except ClientError as err:
        raise _map_aws_exception(err)


def _retrieve_iot_certificate(cloud, id_token):
    """Retrieve the certificate to connect to IoT."""
    # TODO error handling
    return _make_api_call(cloud, id_token, 'device/create').json()


def _make_api_call(cloud, id_token, path, method='POST'):
    """Make a request to our API server."""
    headers = {"Authorization": id_token}
    uri = urljoin(cloud.api_base, path)
    response = requests.request(method, uri, headers=headers)
    return response


def _write_info(cloud, email, cert):
    """Write certificate.

    Pass in None for data to remove authentication for that mode.
    """
    with open(cloud.certificate_pem_path, 'wt') as file:
        file.write(cert['certificate_pem'])

    with open(cloud.secret_key_path, 'wt') as file:
        file.write(cert['secret_key'])

    with open(cloud.user_info_path, 'wt') as file:
        file.write(json.dumps({
            'email': email,
            'thing_name': cert['thing_name']
        }, indent=4))


def _cognito(cloud, **kwargs):
    """Get the client credentials."""
    import botocore
    import boto3
    from warrant import Cognito

    cognito = Cognito(
        user_pool_id=cloud.user_pool_id,
        client_id=cloud.cognito_client_id,
        **kwargs
    )
    cognito.client = boto3.client(
        'cognito-idp',
        region_name=cloud.region,
        config=botocore.config.Config(
            signature_version=botocore.UNSIGNED
        )
    )
    return cognito
