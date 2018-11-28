import os
from functools import wraps

from ..configuration import NullConfig, ConfigKeyError
from .errors import TrackingFailure, UnsupportedTrackingNumber, InvalidTrackingNumber

__carriers = {}

def register_carrier(carrier_iface, config):
    """Register a carrier class, making it available to new Packages

    The new carrier instance will replace an older one with the same string
    representation
    """

    carrier = carrier_iface(config)
    __carriers[str(carrier)] = carrier
    return carrier

def identify_tracking_number(tracking_number):
    """Return the carrier matching the givent tracking number, raises
    UnsupportedTrackingNumber if no match is found
    """

    try:
        return identify_smart_post_number(tracking_number)
    except (InvalidTrackingNumber, UnsupportedTrackingNumber):
        for carrier in __carriers.values():
            if carrier.identify(tracking_number):
                return carrier
        else:
            raise UnsupportedTrackingNumber(tracking_number)

def identify_smart_post_number(tracking_number):
    if len(tracking_number) == 22:
        for carrier in (carrier for carrier in __carriers.values() \
                if carrier.identify(tracking_number)):
            try:
                carrier.track(tracking_number)
            except TrackingFailure as err:
                continue
            else:
                return carrier
        else:
            raise UnsupportedTrackingNumber(tracking_number)
    else:
        raise InvalidTrackingNumber(tracking_number)

def auto_register_carriers(config):
    """Look through the python files in this submodule, registering any classes
    in them that are subclasses of BaseInterface
    """
    carrier_modules = map(lambda m: __import__(m, fromlist='*'),
        [__name__ + '.' + f.rsplit('.', 1)[0] \
            for f in os.listdir(os.path.dirname(__file__)) \
                if f.endswith('.py') and not f.startswith('_')])
    carrier_ifaces = [getattr(m, c) for m in carrier_modules \
        for c in dir(m) \
            if c.endswith('Interface') and \
                issubclass(getattr(m, c), BaseInterface) and \
                getattr(m, c) is not BaseInterface]
    for carrier_iface in carrier_ifaces:
        register_carrier(carrier_iface, config)

class BaseInterface(object):
    """The basic interface for carriers. All registered carriers should inherit
    from this class.
    """
    DEFAULT_CFG = NullConfig()
    DEFAULT_TIMEOUT = 10.0

    def __init__(self, config):
        self._config = config

    def __str__(self):
        return self.SHORT_NAME

    @staticmethod
    def require_valid_tracking_number(func):
        """Intended for wrapping subclasses' track() methods, ensures track()
        is called with a valid tracking number for that carrier.
        """
        @wraps(func)
        def wrapper(self, tracking_number, skip_check=False, *pargs, **kwargs):
            if not self.identify(tracking_number):
                raise InvalidTrackingNumber(tracking_number)
            else:
                return func(self, tracking_number, *pargs, **kwargs)
        return wrapper

    def identify(self, tracking_number):
        raise NotImplementedError()

    def track(self, tracking_number):
        raise NotImplementedError()

    def is_delivered(self, tracking_number, tracking_info=None):
        raise NotImplementedError()

    def url(self, tracking_number):
        return self._url_template.format(tracking_number=tracking_number)

    def _cfg_value(self, *keys):
        """Return the config value from this carrier, looked up with {keys}.
        If the value is not found, the DEFAULT_CFG is fallen back to, then
        a ConfigKeyError is raised if still not found.
        """
        try:
            value = self._config.get_value(self.CONFIG_NS, *keys)
        except ConfigKeyError as err:
            try:
                value = self.DEFAULT_CFG.get_value(self.CONFIG_NS, *keys)
            except ConfigKeyError:
                raise err
        return value
