import requests
from datetime import datetime, date, time, timedelta

from ..configuration import DictConfig
from ..carriers import BaseInterface
from ..xml_dict import dict_to_xml, xml_to_dict
from ..data import TrackingInfo
from .errors import *

class UPSInterface(BaseInterface):
    SHORT_NAME = 'UPS'
    LONG_NAME = SHORT_NAME
    CONFIG_NS = SHORT_NAME
    DEFAULT_CFG = DictConfig({CONFIG_NS:{'lang': 'en-US'}})

    _api_url = 'https://wwwcie.ups.com/ups.app/xml/Track'
    _url_template = 'http://wwwapps.ups.com/WebTracking/processInputRequest?' \
        'TypeOfInquiryNumber=T&InquiryNumber1={tracking_number}'

    def identify(self, tracking_number):
        return (tracking_number.startswith('1Z') and \
            tracking_number[-1].isdigit() and \
            tracking_number.isalnum() and \
            self._check_tracking_code(tracking_number[2:])) or \
            self._is_mi_tracking_number(tracking_number)

    @BaseInterface.require_valid_tracking_number
    def track(self, tracking_number):
        resp = self._send_request(tracking_number)
        return self._parse_response(resp, tracking_number)

    def is_delivered(self, tracking_number, tracking_info=None):
        if tracking_info is None:
            tracking_info = self.track(tracking_number)
        return tracking_info.status.lower() == 'delivered'

    def _is_mi_tracking_number(self, tracking_number):
        return len(tracking_number) == 18 and tracking_number.isdigit()

    def _check_tracking_code(self, tracking_code):
        digits = map(lambda d: int(d) if d.isdigit() else ((ord(d) - 63) % 10),
            tracking_code[:-1].upper())
        total = (sum(digits[1::2]) * 2) + sum(digits[::2])
        check_digit = (10 - (total % 10)) if total % 10 != 0 else 0
        return check_digit == int(tracking_code[-1])

    def _build_access_request(self):
        req = {
            'AccessRequest': {
                'AccessLicenseNumber': self._cfg_value('license_number'),
                'UserId': self._cfg_value('user_id'),
                'Password': self._cfg_value('password'),
            }
        }
        return dict_to_xml(req, {'xml:lang': self._cfg_value('lang')})

    def _build_track_request(self, tracking_number):
        data = {
            'TrackRequest': {
                'Request': {
                    'TransactionReference': {
                        'RequestAction': 'Track',
                    },
                    'RequestOption': '1',
                },
                'TrackingNumber': tracking_number,
            }
        }
        if self._is_mi_tracking_number(tracking_number):
            data['TrackRequest']['TrackingOption'] = '03'
        return dict_to_xml(data)

    def _build_request(self, tracking_number):
        return (self._build_access_request() +
                self._build_track_request(tracking_number))

    def _send_request(self, tracking_number):
        return requests.post(self._api_url, self._build_request(tracking_number), timeout=self.DEFAULT_TIMEOUT).text

    def _parse_response(self, raw, tracking_number):
        try:
            root = xml_to_dict(raw)['TrackResponse']
        except ValueError as err:
            raise TrackingApiFailure(err)

        response = root['Response']
        status_code = response['ResponseStatusCode']
        status_description = response['ResponseStatusDescription']
        # Check status code?

        # we need the service code, some things are treated differently
        try:
            service_code = root['Shipment']['Service']['Code']
        except KeyError:
            raise TrackingApiFailure(root)
        service_description = 'UPS %s' % root['Shipment']['Service']['Description']

        package = root['Shipment']['Package']

        # make activites a list if it's not already
        if type(package['Activity']) != list:
            package['Activity'] = [package['Activity']]

        # this is the last activity, the one we get status info from
        activity = package['Activity'][0]

        # here's the status code, inside the Activity block
        status = activity['Status']['StatusType']['Description']
        status_code = activity['Status']['StatusType']['Code']

        last_update_date = datetime.strptime(activity['Date'], "%Y%m%d").date()
        last_update_time = datetime.strptime(activity['Time'], "%H%M%S").time()
        last_update = datetime.combine(last_update_date, last_update_time)

        # Delivery date is the last_update if delivered, otherwise
        # the estimated delivery date
        if service_code == '031' or status_code == 'D':
            delivery_date = last_update
        elif 'RescheduledDeliveryDate' in package:
            delivery_date = datetime.strptime(
                package['RescheduledDeliveryDate'], "%Y%m%d") + timedelta(hours=18)
        elif 'ScheduledDeliveryDate' in root['Shipment']:
            delivery_date = datetime.strptime(
                root['Shipment']['ScheduledDeliveryDate'], "%Y%m%d") + timedelta(hours=18)
        else:
            delivery_date = None


        # Delivery detail may not always be available either
        if 'Description' in activity['ActivityLocation']:
            delivery_detail = activity['ActivityLocation']['Description']
        else:
            delivery_detail = status

        trackinfo = TrackingInfo(
            tracking_number = tracking_number,
            delivery_date   = delivery_date,
            service         = service_description,
        )

        # add a single event, UPS doesn't seem to support multiple?

        for e in package['Activity']:
            location = self._get_event_location(e['ActivityLocation'])
            edate = datetime.strptime(e['Date'], "%Y%m%d").date()
            etime = datetime.strptime(e['Time'], "%H%M%S").time()
            timestamp = datetime.combine(edate, etime)
            trackinfo.create_event(
                location = location,
                detail = e['Status']['StatusType']['Description'],
                timestamp = timestamp,
            )

        trackinfo.is_delivered = self.is_delivered(None, trackinfo)
        if trackinfo.is_delivered:
            trackinfo.delivery_date = trackinfo.last_update

        return trackinfo

    def _get_event_location(self, location_tag):
        if type(location_tag) == str:
            return location_tag or 'UNKNOWN'
        else:
            if 'Address' in location_tag:
                sub_loc = location_tag['Address']
            else:
                sub_loc = location_tag['TransportFacility']
            keys = ['Code', 'City', 'StateProvinceCode', 'CountryCode']
            location = ','.join(sub_loc[key] for key in keys if key in sub_loc)
            if not location:
                location = 'UNKNOWN'
            return location
