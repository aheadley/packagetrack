"""A simple, generic interface to track packages.

Supported shippers:
    Federal Express, UPS, U.S. Postal Service, DHL, CanadaPost

Basic usage:

    >>> from packagetrack import Package
    >>> package = Package('1Z9999999999999999')
    # Identify packages (UPS, FedEx, and USPS)
    >>> package.carrier
    'UPS'
    # Track packages (UPS only, requires API access)
    >>> info = package.track()
    >>> print info.status
    IN TRANSIT TO
    >>> print info.delivery_date
    2010-06-25 00:00:00
    >>> print info.last_update
    2010-06-19 00:54:00
    # Get tracking URLs
    >>> print package.url
    http://wwwapps.ups.com/WebTracking/processInputRequest?TypeOfInquiryNumber=T&InquiryNumber1=1Z9999999999999999

Configuration:

To enable package tracking (not just finding URLs or matching TNs to carriers),
you will need to get API credentials for most of the carriers you wish to use.
The default configuration method is to read the config values from
~/.packagetrack, which looks like this:

    [UPS]
    license_number = XXXXXXXXXXXXXXXX
    user_id = XXXX
    password = XXXX

    [FedEx]
    key = XXXXXXXXXXXXXXXX
    password = XXXXXXXXXXXXXXXXXXXXXXXXX
    account_number = #########
    meter_number = #########

    [USPS]
    userid = XXXXXXXXXXXX
    password = XXXXXXXXXXXX

    [CanadaPost]
    username = XXXXXXXXXXXXXXXX
    password = XXXXXXXXXXXXXXXXXXXXXX

You can specify an alternate location for the config file like so:

    >>> from packagetrack.configuration import DotFileConfig
    >>> cfg = DotFileConfig('/path/to/file')
    >>> packagetrack.auto_register_carriers(cfg)

Alternatively, you can provide a different type of config like the
DictConfig or making another type (like one that pulls values from a database).
"""

__credits__     = ['Scott Torborg', 'Michael Stella', 'Alex Headley']
__authors__     = ', '.join(__credits__)
__license__     = 'GPL'
__maintainer__  = __credits__[2]
__status__      = 'Development'
__version__     = '0.4.2'

from .configuration import ConfigError, DotFileConfig, NullConfig
from .data import Package
from .carriers import auto_register_carriers

try:
    config = DotFileConfig()
except (ConfigError, ImportError):
    config = NullConfig()

auto_register_carriers(config)
