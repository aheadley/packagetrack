import datetime
import hashlib
import requests
from pytz import timezone

from ..carriers import BaseInterface
from ..configuration import DictConfig
from ..data import TrackingInfo, TrackingEvent
from ..xml_dict import xml_to_dict
from .errors import *

class DHLInterface(BaseInterface):
    SHORT_NAME = 'DHL'
    LONG_NAME = SHORT_NAME
    CONFIG_NS = SHORT_NAME
    DEFAULT_CFG = DictConfig({CONFIG_NS:{
        'site_id': 'DServiceVal',
        'password': 'testServVal',
        'server': 'test',
        'timezone': 'America/Detroit',
        'lang': 'en',
    }})

    _servers = {
        'production': 'xmlpi-ea.dhl.com',
        'test': 'xmlpitest-ea.dhl.com'
    }

    _url_template = 'http://www.dhl.com/content/g0/en/express/tracking.shtml?' \
        'brand=DHL&AWB={tracking_number}'

    _time_format = '%Y-%m-%dT%H:%M:%S'
    _request_url = 'https://{server}/XMLShippingServlet'
    _request_template = '''<?xml version="1.0" encoding="UTF-8"?>
<req:KnownTrackingRequest xmlns:req="http://www.dhl.com"
                        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                        xsi:schemaLocation="http://www.dhl.com
                        TrackingRequestKnown.xsd">
    <Request>
        <ServiceHeader>
            <MessageTime>{message_time}</MessageTime>
            <MessageReference>{message_reference}</MessageReference>
            <SiteID>{site_id}</SiteID>
            <Password>{password}</Password>
        </ServiceHeader>
    </Request>
    <LanguageCode>{language_code}</LanguageCode>
    <AWBNumber>{awb_number}</AWBNumber>
    <LevelOfDetails>ALL_CHECK_POINTS</LevelOfDetails>
    <PiecesEnabled>S</PiecesEnabled>
</req:KnownTrackingRequest>'''

    def identify(self, tracking_number):
        return {
            10: lambda tn: tn.isdigit(),
            11: lambda tn: tn.isdigit(),
        }.get(len(tracking_number), lambda tn: False)(tracking_number)

    @BaseInterface.require_valid_tracking_number
    def track(self, tracking_number):
        req = self._format_request(tracking_number)
        url = self._request_url.format(
            server=self._servers[self._cfg_value('server')])
        return self._parse_response(requests.post(url, req).text)

    def is_delivered(self, tracking_number, tracking_info=None):
        if tracking_info is None:
            tracking_info = self.track(tracking_number)
        return tracking_info.status.lower().endswith('delivered')

    def _parse_response(self, raw_api_response):
        try:
            resp = xml_to_dict(raw_api_response)['req:TrackingResponse']['AWBInfo']
        except KeyError as err:
            raise TrackingFailure(err)
        if resp['Status']['ActionStatus'] != u'success':
            try:
                msg = resp['Status']['Condition']['ConditionData']
            except KeyError:
                msg = resp['Status']['ActionStatus']
            raise TrackingApiFailure(msg)
        info = TrackingInfo(
            tracking_number=resp['AWBNumber'],
        )
        info.events = info.sort_events(self._parse_events(
            resp['ShipmentInfo']['ShipmentEvent']))
        info.is_delivered = self.is_delivered(None, info)
        if info.is_delivered:
            info.delivery_date = info.last_update
        return info

    def _parse_events(self, events):
        if not isinstance(events, list):
            events = [events]
        return (TrackingEvent(
            timestamp=datetime.datetime.strptime(
                '{Date}T{Time}'.format(**event),
                self._time_format),
            location=','.join(s.strip() \
                for s in event['ServiceArea']['Description'].split('-') if s.strip()),
            detail=' '.join(s.strip() for s in event['ServiceEvent']['Description'].split('\n')).replace(
                event['ServiceArea']['Description'], '').strip().replace(
                ' in', '').replace(' at', '')) \
            for event in events)

    def _format_request(self, awb_number):
        message_time = datetime.datetime.now(timezone(self._cfg_value('timezone'))).replace(microsecond=0).isoformat()
        message_reference = self._generate_message_reference(awb_number, message_time)
        return self._request_template.format(
            message_time=message_time,
            message_reference=message_reference,
            site_id=self._cfg_value('site_id'),
            password=self._cfg_value('password'),
            language_code=self._cfg_value('lang'),
            awb_number=awb_number)

    def _generate_message_reference(self, awb_number, message_time):
        return hashlib.md5('|'.join(
            [awb_number, message_time, self._cfg_value('site_id'),
                self._cfg_value('password')])).hexdigest()
