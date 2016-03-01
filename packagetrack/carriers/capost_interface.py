import suds
import datetime

from ..data import TrackingInfo
from ..carriers import BaseInterface
from .errors import *

class CanadaPostInterface(BaseInterface):
    SHORT_NAME = 'CAPost'
    LONG_NAME = 'CanadaPost'
    CONFIG_NS = LONG_NAME
    _soap_wsdl = 'http://www.canadapost.ca/cpo/mc/assets/wsdl/developers/track.wsdl'
    _soap_endpoint = 'https://soa-gw.canadapost.ca/vis/soap/track'
    _url_template = 'http://www.canadapost.ca/cpotools/apps/track/' \
        'personal/findByTrackNumber?trackingNumber={tracking_number}&LOCALE=en'
    _client = None

    def identify(self, tracking_number):
        """Check if a tracking number is valid for this service
        """
        return {
            11: lambda tn: tn[:2].isalpha() and tn.endswith('CA'),
            13: lambda tn: tn[:2].isalpha() and tn.endswith('CA'),
            16: lambda tn: tn.isdigit(),
        }.get(len(tracking_number), lambda tn: False)(tracking_number)

    @BaseInterface.require_valid_tracking_number
    def track(self, tracking_number):
        client = self._get_client()
        try:
            summary = client.service.GetTrackingSummary(
                locale='EN', pin=tracking_number)
            detail = client.service.GetTrackingDetail(
                locale='EN', pin=tracking_number)
        except suds.WebFault as e:
            raise TrackingApiFailure(e)
        info = self._parse_response(summary, detail)
        info.tracking_number = tracking_number
        info.is_delivered = self.is_delivered(None, info)
        if info.is_delivered:
            info.delivery_date = info.last_update
        return info

    def is_delivered(self, tracking_number, tracking_info=None):
        if tracking_info is None:
            tracking_info = self.track(tracking_number)
        return tracking_info.status.lower().endswith('delivered')

    def _get_client(self):
        if self._client is None:
            sec_token = suds.wsse.Security()
            sec_token.tokens.append(suds.wsse.UsernameToken(
                self._cfg_value('username'), self._cfg_value('password')))
            self._client = suds.client.Client(self._soap_wsdl,
                location=self._soap_endpoint,
                wsse=sec_token)
        return self._client

    def _get_keys(self, reply):
        return [k for k in dir(reply) if not k.startswith('_')]

    def _parse_response(self, summary_response, detail_response):
        if 'messages' in self._get_keys(summary_response):
            raise TrackingApiFailure(summary_response['messages'])
        elif 'messages' in self._get_keys(detail_response):
            raise TrackingApiFailure(detail_response['messages'])
        summary = summary_response['tracking-summary']['pin-summary'][0]
        details = detail_response['tracking-detail']
        delivery_date = datetime.datetime.strptime(
            details['expected-delivery-date'],
            '%Y-%m-%d')
        service = details['service-name']
        info = TrackingInfo(
            tracking_number=None,
            delivery_date=delivery_date,
            service=service,
        )
        for event in details['significant-events']['occurrence'][::-1]:
            date = datetime.datetime.strptime(event['event-date'], '%Y-%m-%d').date()
            time = datetime.datetime.strptime(event['event-time'], '%H:%M:%S').time()
            info.create_event(
                timestamp=datetime.datetime.combine(date,time),
                detail=event['event-description'],
                location=','.join(s for s in [event['event-site'], event['event-province']] if s))
        return info
