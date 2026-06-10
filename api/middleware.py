"""Attach a correlation/request ID to each request for log tracing (design §25)."""

from __future__ import annotations

import logging
import uuid

logger = logging.getLogger("fuelroute.request")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.request_id = request_id
        response = self.get_response(request)
        response[REQUEST_ID_HEADER] = request_id
        return response
