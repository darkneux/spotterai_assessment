"""Domain exceptions raised by routing/geocoding, mapped to HTTP codes in the API."""


class RoutingError(Exception):
    """Raised when the routing provider cannot produce a route (-> 502/503)."""


class GeocodingError(Exception):
    """Raised when a location string cannot be geocoded (-> 400/422)."""


class OutsideUSAError(Exception):
    """Raised when a resolved coordinate falls outside the USA (-> 400)."""
