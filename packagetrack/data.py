from operator import attrgetter
from requests import ConnectionError
from requests.exceptions import ReadTimeout
from urllib2 import URLError

from .carriers import identify_tracking_number
from .carriers.errors import TrackingNetworkFailure

class Package(object):
    """A package to be tracked."""

    _carrier = None
    _repr_template = '<Package(carrier={p.carrier!s}, tracking_number={p.tracking_number!r})>'

    def __init__(self, tracking_number, carrier=None):
        self.tracking_number = tracking_number
        if carrier is not None:
            self._carrier = carrier

    def __repr__(self):
        return self._repr_template.format(p=self)

    @property
    def carrier(self):
        """Get the name of this package's carrier
        """

        if self._carrier is None:
            self._carrier = identify_tracking_number(self.tracking_number)
        return self._carrier

    def track(self):
        """Get the tracking info for this package, returns a TrackingInfo object
        """

        try:
            return self.carrier.track(self.tracking_number)
        except (ConnectionError, URLError, ReadTimeout) as err:
            raise TrackingNetworkFailure(err)

    @property
    def url(self):
        """Returns a URL that can be used to go to the carrier's
        tracking website, to track this package.
        """

        return self.carrier.url(self.tracking_number)

class TrackingInfo(dict):
    """Generic tracking information object returned by a tracking request

    Only the tracking_number, delivery_date, location, last_update and status
    are guaranteed to be available, but a carrier may add additional attributes/info.

    timestamp and last_update will always be datetime objects, the delivery_date
    will be as well, unless it wasn't provided in which case it will be None
    """

    _repr_template = '<TrackingInfo(tracking_number={i.tracking_number!r}, timestamp={ts})>'

    def __init__(self, tracking_number, delivery_date=None, is_delivered=False, **kwargs):
        self.tracking_number = tracking_number
        self.delivery_date = delivery_date
        self.is_delivered = is_delivered
        self.events = []
        self.update(kwargs)

    def __getattr__(self, name):
        return self[name]

    def __setattr__(self, name, val):
        self[name] = val

    def __repr__(self):
        return self._repr_template.format(i=self, ts=self.last_update.isoformat())

    @property
    def location(self):
        """A shortcut to the location of the latest event for this package
        """
        return self.events[-1].location

    @property
    def last_update(self):
        """Shortcut to the timestamp of the latest event for this package
        """
        return self.events[-1].timestamp

    @property
    def status(self):
        """Shortcut to the detail of the latest event for this package
        """
        return self.events[-1].detail

    def create_event(self, timestamp, location, detail, **kwargs):
        """Create a new event with these attributes, events do not need to be added
        in order
        """
        event = TrackingEvent(timestamp, location, detail)
        event.update(kwargs)
        return self.add_event(event)

    def add_event(self, event):
        """Add a new TrackingEvent object to this package, events do not need to
        be added in order
        """
        self.events = self.sort_events(self.events + [event])
        return event

    def sort_events(self, events=None):
        """Sort a list of events by timestamp, defaults to this package's events
        """
        if events is None:
            events = self.events
        return sorted(events, key=attrgetter('timestamp'))

class TrackingEvent(dict):
    """An individual tracking event, like a status change

    Only the timestamp, location, and detail attributes are required, but a
    carrier may add other information if available. timestamp is always a
    datetime object.
    """
    _repr_template = '<TrackingEvent(timestamp={ts}, location={e.location!r}, detail={e.detail!r})>'

    def __init__(self, timestamp, location, detail, **kwargs):
        self.timestamp = timestamp
        self.location = location
        self.detail = detail
        self.update(kwargs)

    def __getattr__(self, name):
        return self[name]

    def __setattr__(self, name, val):
        self[name] = val

    def __repr__(self):
        return self._repr_template.format(e=self, ts=self.timestamp.isoformat())
