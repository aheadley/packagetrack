import datetime
import requests
import json

from ..configuration import DictConfig
from ..data import TrackingInfo
from ..carriers import BaseInterface
from .errors import *

class PrestigeInterface(BaseInterface):
    SHORT_NAME = 'Prestige'
    LONG_NAME = 'Prestige Delivery Systems, Inc'
    CONFIG_NS = 'PS'
    DEFAULT_CFG = DictConfig({CONFIG_NS:{}})

    _API_URL = 'http://www.prestigedelivery.com/TrackingHandler.ashx'
    
    _url_template = 'http://www.prestigedelivery.com/trackpackage.aspx?{tracking_number}'

    @BaseInterface.require_valid_tracking_number
    def track(self, tracking_number):
        return self._parse_response(self._send_request(tracking_number))

    def identify(self, tracking_number):
        return len(tracking_number) == 10 and \
            tracking_number[0] == 'P' and \
            tracking_number[1].isalpha() and \
            tracking_number[2:].isdigit()

    def is_delivered(self, tracking_number, tracking_info=None):
        if tracking_info is None:
            tracking_info = self.track(tracking_number)
        return tracking_info.status.lower() == 'delivered'

    def _send_request(self, tracking_number):
        try:
            resp = requests.get(self._API_URL,
                params={'trackingNumbers': tracking_number})
        except requests.exceptions.RequestException as err:
            raise TrackingNetworkFailure(err)
        return resp.content

    def _parse_response(self, raw_response):
        try:
            resp_data = json.loads(raw_response)[0]
        except ValueError as err:
            raise TrackingApiFailure(err)
        if resp_data['TrackingEventHistory'][0]['EventCode'].startswith('ERROR_'):
            raise TrackingApiFailure('%s: %s' % (
                resp_data['TrackingEventHistory'][0]['EventCode'],
                resp_data['TrackingEventHistory'][0]['EventCodeDesc']))
        info = TrackingInfo(tracking_number=resp_data['TrackingNumber'],
            delivery_date=self._parse_delivery_date(resp_data))
        for event_data in resp_data['TrackingEventHistory']:
            event_ts = self._parse_event_timestamp(event_data)
            event_loc = '%s, %s' % (
                event_data['ELCity'].strip(), event_data['ELState'].strip())
            event_detail = event_data['EventCodeDesc'].strip()
            info.create_event(event_ts, event_loc, event_detail)
        info.is_delivered = self.is_delivered(None, info)
        if info.is_delivered:
            info.delivery_date = info.last_update
        return info

    def _parse_event_timestamp(self, event_data):
        date = datetime.datetime.strptime(event_data['serverDate'], '%m/%d/%Y').date()
        time = datetime.datetime.strptime(event_data['serverTime'], '%I:%M %p').time()
        return datetime.datetime.combine(date, time)

    def _parse_delivery_date(self, resp_data):
        ts = int(resp_data['TrackingEventHistory'][0]['SchdDateTime'][6:-5])
        return datetime.datetime.fromtimestamp(ts)
