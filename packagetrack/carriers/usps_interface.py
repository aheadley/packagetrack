import datetime
import requests

from ..configuration import DictConfig
from ..data import TrackingInfo
from ..carriers import BaseInterface
from ..xml_dict import xml_to_dict
from .errors import *

class USPSInterface(BaseInterface):
    SHORT_NAME = 'USPS'
    LONG_NAME = 'U.S. Postal Service'
    CONFIG_NS = SHORT_NAME
    DEFAULT_CFG = DictConfig({CONFIG_NS:{'server': 'production'}})

    _api_urls = {
        'secure_test': 'https://secure.shippingapis.com/ShippingAPITest.dll?' \
            'API=TrackV2&XML=',
        'test':        'http://testing.shippingapis.com/ShippingAPITest.dll?' \
            'API=TrackV2&XML=',
        'production':  'http://production.shippingapis.com/ShippingAPI.dll?' \
            'API=TrackV2&XML=',
        'secure':      'https://secure.shippingapis.com/ShippingAPI.dll?' \
            'API=TrackV2&XML=',
    }
    _service_types = {
        'EA': 'Express Mail',
        'EC': 'Express Mail International',
        'CP': 'Priority Mail International',
        'RA': 'Registered Mail Domestic',
        'RF': 'Registered Mail Foreign',
        # 'EJ': 'something?',
    }
    _url_template = 'https://tools.usps.com/go/TrackConfirmAction.action?tLabels={tracking_number}'
    _request_xml = '<TrackFieldRequest USERID="{userid}">' \
        '<TrackID ID="{tracking_number}"/></TrackFieldRequest>'

    @BaseInterface.require_valid_tracking_number
    def track(self, tracking_number):
        resp = self._send_request(tracking_number)
        return self._parse_response(resp, tracking_number)

    def identify(self, tracking_number):
        return {
            13: lambda tn: \
                tn[0:2].isalpha() and tn[2:9].isdigit() and tn[11:13].isalpha(),
            20: lambda tn: tn.isdigit() and tn.startswith('0'),
            22: lambda tn: tn.isdigit(),
            30: lambda tn: tn.isdigit(),
        }.get(len(tracking_number), lambda tn: False)(tracking_number)

    def is_delivered(self, tracking_number, tracking_info=None):
        if tracking_info is None:
            tracking_info = self.track(tracking_number)
        return tracking_info.status.lower() == 'delivered'

    def _build_request(self, tracking_number):
        return self._request_xml.format(
            userid=self._cfg_value('userid'),
            tracking_number=tracking_number)

    def _parse_response(self, raw, tracking_number):
        rsp = xml_to_dict(raw)
        # this is a system error
        if 'Error' in rsp:
            error = rsp['Error']['Description']
            raise TrackingApiFailure(error)

        # this is a result with an error, like "no such package"
        try:
            if 'Error' in rsp['TrackResponse']['TrackInfo']:
                error = rsp['TrackResponse']['TrackInfo']['Error']['Description']
                raise TrackingNumberFailure(error)
        except KeyError:
            raise TrackingApiFailure(rsp)

        # make sure the events list is a list
        try:
            events = rsp['TrackResponse']['TrackInfo']['TrackDetail']
        except KeyError:
            events = []
        else:
            if type(events) != list:
                events = [events]
        summary = rsp['TrackResponse']['TrackInfo']['TrackSummary']

        # USPS doesn't return this, so we work it out from the tracking number
        service_description = self._service_types.get(tracking_number[0:2], 'USPS')

        trackinfo = TrackingInfo(
            tracking_number = tracking_number,
            service         = service_description,
        )

        # add the summary event, USPS doesn't duplicate it in the event log,
        # but we want it there
        trackinfo.create_event(
            location=self._getTrackingLocation(summary),
            timestamp=self._getTrackingDate(summary),
            detail=summary['Event'])

        for e in events:
            trackinfo.create_event(
                location = self._getTrackingLocation(e),
                timestamp= self._getTrackingDate(e),
                detail   = e['Event'],
            )

        trackinfo.is_delivered = self.is_delivered(None, trackinfo)
        if trackinfo.is_delivered:
            trackinfo.delivery_date = trackinfo.last_update

        return trackinfo

    def _send_request(self, tracking_number):
        url = self._api_urls[self._cfg_value('server')] + \
            self._build_request(tracking_number)
        return requests.get(url).text

    def _getTrackingDate(self, node):
        """Returns a datetime object for the given node's
        <EventTime> and <EventDate> elements"""
        try:
            date = datetime.datetime.strptime(node['EventDate'], '%B %d, %Y').date()
        except ValueError:
            date = datetime.datetime.now() - datetime.timedelta(7)
        time = datetime.datetime.strptime(node['EventTime'], '%I:%M %p').time() \
            if node['EventTime'] else datetime.time(0, 0, 0)
        return datetime.datetime.combine(date, time)

    def _getTrackingLocation(self, node):
        """Returns a location given a node that has
            EventCity, EventState, EventCountry elements"""
        return ','.join(
            node[key] for key in ('Event'+i for i in ['City', 'State', 'Country']) \
                if node[key]) or \
            'USA'
