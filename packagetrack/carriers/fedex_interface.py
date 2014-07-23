from datetime import datetime, date, time

from fedex.config import FedexConfig
from fedex.base_service import FedexError
from fedex.services.track_service import FedexTrackRequest, FedexInvalidTrackingNumber

from ..data import TrackingInfo
from ..carriers import BaseInterface
from .errors import *

class FedexInterface(BaseInterface):
    SHORT_NAME = 'FedEx'
    LONG_NAME = 'Federal Express'
    CONFIG_NS = SHORT_NAME
    _url_template = 'http://www.fedex.com/Tracking?tracknumbers={tracking_number}'

    @BaseInterface.require_valid_tracking_number
    def track(self, tracking_number):
        track = FedexTrackRequest(self._get_cfg())

        track.TrackPackageIdentifier.Type = 'TRACKING_NUMBER_OR_DOORTAG'
        track.TrackPackageIdentifier.Value = tracking_number
        track.IncludeDetailedScans = True

        # Fires off the request, sets the 'response' attribute on the object.
        try:
            track.send_request()
        except FedexInvalidTrackingNumber as err:
            raise TrackingNumberFailure(err)
        except (FedexError, Exception) as err:
            raise TrackingApiFailure(err)

        # TODO: I haven't actually seen an unsuccessful query yet
        if track.response.HighestSeverity != "SUCCESS":
            raise TrackingApiFailure("%d: %s" % (
                    track.response.Notifications[0].Code,
                    track.response.Notifications[0].LocalizedMessage
                    ))

        return self._parse_response(track.response.TrackDetails[0], tracking_number)

    def identify(self, tracking_number):
        """Validate the tracking number"""

        return {
            12: lambda tn: self._validate_express(tn) or True,
            15: self._validate_ground96,
            20: lambda tn: tn.startswith('96') and self._validate_ground96(tn),
            22: lambda tn: tn.isdigit() or (tn.startswith('00') and \
                self._validate_ssc18(tn)),
        }.get(len(tracking_number), lambda tn: False)(tracking_number)

    def is_delivered(self, tracking_number, tracking_info=None):
        if tracking_info is None:
            tracking_info = self.track(tracking_number)
        return tracking_info.status.lower() == 'delivered'

    def _parse_response(self, rsp, tracking_number):
        """Parse the track response and return a TrackingInfo object"""

        # test status code, return actual delivery time if package
        # was delivered, otherwise estimated target time
        if rsp.StatusCode == 'DL':
            delivery_date = rsp.ActualDeliveryTimestamp

            # this may not be present
            try:
                delivery_detail = rsp.Events[0].StatusExceptionDescription
            except AttributeError:
                delivery_detail = None

            last_update = delivery_date
            try:
                location = ','.join((
                                    rsp.ActualDeliveryAddress.City,
                                    rsp.ActualDeliveryAddress.StateOrProvinceCode,
                                    rsp.ActualDeliveryAddress.CountryCode,
                                ))
            except AttributeError:
                location = 'UNKNOWN'

        else:
            delivery_detail = None
            try:
                delivery_date = datetime.combine(rsp.EstimatedDeliveryTimestamp, time(18))
            except AttributeError:
                delivery_date = None
            last_update = rsp.Events[0].Timestamp
            location = self._getTrackingLocation(rsp.Events[0])


        # a new tracking info object
        trackinfo = TrackingInfo(
            tracking_number = tracking_number,
            delivery_date   = delivery_date,
            delivery_detail = delivery_detail,
            service         = rsp.ServiceType,
        )

        # now add the events
        for e in rsp.Events:
            trackinfo.create_event(
                location = self._getTrackingLocation(e),
                timestamp= e.Timestamp,
                detail   = e.EventDescription,
            )

        trackinfo.is_delivered = self.is_delivered(None, trackinfo)
        if trackinfo.is_delivered:
            trackinfo.delivery_date = trackinfo.last_update

        return trackinfo


    def _getTrackingLocation(self, e):
        """Returns a nicely formatted location for a given event"""
        try:
            return ','.join((
                            e.Address.City,
                            e.Address.StateOrProvinceCode,
                            e.Address.CountryCode,
                        ))
        except:
            return 'UNKNOWN'


    def _get_cfg(self):
        """Makes and returns a FedexConfig object from the packagetrack
           configuration.  Caches it, so it doesn't create each time."""

        return FedexConfig(
            key = self._cfg_value('key'),
            password = self._cfg_value('password'),
            account_number = self._cfg_value('account_number'),
            meter_number = self._cfg_value('meter_number'),
            use_test_server     = False,
            express_region_code = 'US',
        )

    def _validate_ground96(self, tracking_number):
        """Validates ground code 128 ("96") bar codes

            15-digit form:

                    019343586678996
        shipper ID: -------
        package ID:        -------
        checksum:                 -

                22-digit form:
                    9611020019343586678996
        UCC/EAN id: --
        SCNC:         --
        class of svc:   --
        shipper ID:        -------
        package ID:               -------
        checksum:                        -

        """

        rev = tracking_number[::-1]

        eventotal = 0
        oddtotal = 0
        for i in range(1,15):
            if i % 2:
                eventotal += int(rev[i])
            else:
                oddtotal += int(rev[i])

        check = 10 - ((eventotal * 3 + oddtotal) % 10)

        # compare with the checksum digit, which is the last digit
        return check == int(tracking_number[-1:])

    def _validate_ssc18(self, tracking_number):
        """Validates SSC18 tracking numbers"""

        rev = tracking_number[::-1]

        eventotal = 0
        oddtotal = 0
        for i in range(1,19):
            if i % 2:
                eventotal += int(rev[i])
            else:
                oddtotal += int(rev[i])

        check = 10 - ((eventotal * 3 + oddtotal) % 10)

        # compare with the checksum digit, which is the last digit
        return check == int(tracking_number[-1:])


    def _validate_express(self, tracking_number):
        """Validates Express tracking numbers"""

        basenum = tracking_number[0:10]
        
        if not basenum.isdigit():
            return False

        sums = []
        mult = 1
        total = 0
        for digit in basenum[::-1]:
            sums.append(int(digit) * mult)
            total = total + (int(digit) * mult)

            if mult == 1: mult = 3
            if mult == 3: mult = 7
            if mult == 7: mult = 1

        check = total % 11
        if check == 10:
            check = 0

        # compare with the checksum digit, which is the last digit
        return check == int(tracking_number[-1:])
