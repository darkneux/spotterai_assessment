"""
Uniform error envelope for the API:

    {"error": {"code": ..., "message": ..., "details": ..., "request_id": ...}}

`api_exception_handler` is wired as DRF's DEFAULT exception handler so that
validation errors and unexpected exceptions share the same shape as the
domain-specific errors returned explicitly by the views.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger("fuelroute.api")


def error_body(code: str, message: str, request=None, details=None) -> dict:
    body = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    if request is not None and getattr(request, "request_id", None):
        body["request_id"] = request.request_id
    return {"error": body}


def error_response(code, message, http_status, request=None, details=None) -> Response:
    return Response(error_body(code, message, request, details), status=http_status)


def api_exception_handler(exc, context):
    request = context.get("request")
    response = drf_exception_handler(exc, context)

    if response is not None:
        # DRF already classified this (e.g. validation error). Re-wrap it.
        code = "validation_error" if response.status_code == 400 else "error"
        response.data = error_body(code, "Request could not be processed.",
                                   request, details=response.data)
        return response

    # Anything uncaught is a server error.
    logger.exception("unhandled exception in API")
    return error_response(
        "server_error",
        "An unexpected error occurred.",
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        request,
    )
