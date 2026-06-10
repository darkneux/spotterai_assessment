"""Minimal Google encoded-polyline codec (precision 5) for route geometry."""

from __future__ import annotations


def _encode_value(value: int) -> str:
    value = ~(value << 1) if value < 0 else (value << 1)
    chunks = []
    while value >= 0x20:
        chunks.append((0x20 | (value & 0x1F)) + 63)
        value >>= 5
    chunks.append(value + 63)
    return "".join(chr(c) for c in chunks)


def encode(coords: list[tuple[float, float]]) -> str:
    """Encode a list of (lat, lng) into a polyline string."""
    out = []
    prev_lat = prev_lng = 0
    for lat, lng in coords:
        ilat = round(lat * 1e5)
        ilng = round(lng * 1e5)
        out.append(_encode_value(ilat - prev_lat))
        out.append(_encode_value(ilng - prev_lng))
        prev_lat, prev_lng = ilat, ilng
    return "".join(out)


def decode(polyline: str) -> list[tuple[float, float]]:
    """Decode a polyline string into a list of (lat, lng)."""
    coords: list[tuple[float, float]] = []
    index = lat = lng = 0
    length = len(polyline)
    while index < length:
        for is_lng in (False, True):
            shift = result = 0
            while True:
                b = ord(polyline[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if (result & 1) else (result >> 1)
            if is_lng:
                lng += delta
            else:
                lat += delta
        coords.append((lat / 1e5, lng / 1e5))
    return coords
