# -*- coding: utf-8 -*-

import datetime
import re

import requests
import bs4

from ..configuration import DictConfig
from ..data import TrackingInfo
from ..carriers import BaseInterface
from .errors import *

def _find(tag, *args, **kwargs):
    try:
        contents = tag.find(*args, **kwargs).text.strip()
    except AttributeError:
        contents = ''
    return contents

class AMZLInterface(BaseInterface):
    SHORT_NAME = 'AMZL'
    LONG_NAME = 'Amazon Logistics'
    CONFIG_NS = SHORT_NAME
    DEFAULT_CFG = DictConfig({CONFIG_NS:{
        'timezone': 'America/Detroit',  
    }})

    _url_template = 'https://www.amazon.com/progress-tracker/package/?itemId={item_id}&orderId={order_id}&packageIndex={package_idx}'
    _url_template_keys = ('order_id', 'item_id', 'package_idx')
    _IGNORE_TAG_CLASSES = ('tracking-event-carrier-header', 'tracking-event-trackingId-text', 'tracking-event-timezoneLabel')   
    _TN_REGEX = r'\d{3}-\d{7}-\d{7}(?::\w+)?'

    def identify(self, tracking_number):
        return bool(re.match(self._TN_REGEX, tracking_number))

    def is_delivered(self, tracking_number, tracking_info=None):
        if tracking_info is None:
            tracking_info = self.track(tracking_number)
        return tracking_info.status.lower() == 'delivered'

    BaseInterface.require_valid_tracking_number
    def track(self, tracking_number):
        info = TrackingInfo(tracking_number)

        data = self._get_tracking_data(**self._parse_tracking_number(tracking_number))

        for event in data['events']:
            info.create_event(
                location=event['location'],
                timestamp=event['timestamp'],
                detail=event['message'])
        info.is_delivered = self.is_delivered(None, info)
        if info.is_delivered:
            info.delivery_date = info.last_update

        return info

    def url(self, tracking_number):
        return self._url_template.format(**self._parse_tracking_number(tracking_number))

    def _parse_tracking_number(self, tracking_number):
        parts = tracking_number.split(':')
        parsed = dict(zip(self._url_template_keys, list(parts) + [0, 0, 0]))
        return parsed

    def _get_tracking_data(self, order_id, item_id=0, package_idx=0):
        tracking_url = self._url_template.format(
            order_id=order_id, item_id=item_id, package_idx=package_idx)

        try:
            response = requests.get(tracking_url, timeout=10.0)
        except Exception as err:
            raise TrackingApiFailure(err)

        if not response.ok:
            raise TrackingApiFailure('Amazon returned HTTP status: %s' % response.status_code)
        if 'carrierRelatedInfo-trackingId-text' not in response.content:
            raise TrackingNumberFailure('No shipment found')

        soup = bs4.BeautifulSoup(response.content, 'html.parser')

        return self._parse_tracking_response(soup)

    def _parse_tracking_response(self, soup):
        tracking_data = {
            'id': None,
            'primary-status': None,
            'secondary-status': None,
            'milestone-message': None,
            'exception-source': None,
            'exception-message': None,
            'events': [],
        }

        # if not any('carrierRelatedInfo-trackingId-text' in line for line in soup.contents):
        #     raise TrackingNumberFailure('No shipment found')

        tracking_data['id'] = _find(soup, class_='carrierRelatedInfo-trackingId-text').split()[-1]
        tracking_data['primary-status'] = _find(soup, id='primaryStatus')
        tracking_data['secondary-status'] = _find(soup, id='secondaryStatus')
        tracking_data['milestone-message'] = _find(soup, class_='milestone-primaryMessage')
        tracking_data['exception-source'] = _find(soup, class_='lastExceptionSource')
        tracking_data['exception-message'] = _find(soup, class_='lastExceptionExplanation')
        tracking_data['events'] = [
            {
                'timestamp': self._parse_timestamp(u' '.join([
                    _find(tag, class_='tracking-event-time'),
                    _find(container_tag, class_='tracking-event-date')]).strip()),
                'message': _find(tag, class_='tracking-event-message'),
                'location': _find(tag, class_='tracking-event-location'),
            }
            for container_tag in soup.select('#tracking-events-container > * > .a-row')
            if all(attr not in container_tag.attrs['class'] for attr in self._IGNORE_TAG_CLASSES)
            for tag in container_tag.select('.a-spacing-large')
            if all(attr not in tag.attrs['class'] for attr in self._IGNORE_TAG_CLASSES)
        ]

        return tracking_data    

    def _parse_timestamp(self, timestamp, year=None):
        if year is None:
            year = str(datetime.datetime.now().year)
        timestamp = ' '.join([timestamp, year])

        try:
            timestamp = datetime.datetime.strptime(timestamp, '%I:%M %p %A, %B %d %Y')
        except ValueError as err:
            try:
                timestamp = datetime.datetime.strptime(timestamp, '%A, %B %d %Y')
            except ValueError as err:
                timestamp = datetime.datetime()

        return timestamp
