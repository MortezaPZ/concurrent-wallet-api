"""Domain errors and a single, uniform API error envelope."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class WalletError(Exception):
    """Base class for domain errors that map onto an HTTP response."""

    code = "wallet_error"
    message = "Wallet operation failed."
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str | None = None, **details: Any) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = details


class WalletNotFoundError(WalletError):
    code = "wallet_not_found"
    message = "Wallet does not exist."
    status_code = status.HTTP_404_NOT_FOUND


class InsufficientFundsError(WalletError):
    code = "insufficient_funds"
    message = "Balance is not sufficient for this debit."
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY

    def __init__(self, *, balance: Decimal, requested: Decimal) -> None:
        super().__init__(
            balance=str(balance),
            requested=str(requested),
            shortfall=str(requested - balance),
        )


class IdempotencyKeyConflictError(WalletError):
    code = "idempotency_key_conflict"
    message = "This request_id was already used with a different amount."
    status_code = status.HTTP_409_CONFLICT

    def __init__(
        self, *, request_id: str, existing_amount: Decimal, requested_amount: Decimal
    ) -> None:
        super().__init__(
            request_id=request_id,
            existing_amount=str(existing_amount),
            requested_amount=str(requested_amount),
        )


STATUS_FALLBACK_CODES = {
    status.HTTP_403_FORBIDDEN: "permission_denied",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_406_NOT_ACCEPTABLE: "not_acceptable",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "unsupported_media_type",
    status.HTTP_429_TOO_MANY_REQUESTS: "throttled",
}


def error_payload(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def api_exception_handler(exc: Exception, context: dict) -> Response | None:
    """Render every error - domain or framework - with the same shape."""
    if isinstance(exc, WalletError):
        return Response(
            error_payload(exc.code, exc.message, exc.details),
            status=exc.status_code,
        )

    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    detail = response.data
    if isinstance(detail, dict) and set(detail) == {"detail"}:
        code = getattr(exc, "default_code", None) or STATUS_FALLBACK_CODES.get(
            response.status_code, "error"
        )
        response.data = error_payload(str(code), str(detail["detail"]))
    else:
        response.data = error_payload("validation_error", "Request payload is invalid.", detail)
    return response
