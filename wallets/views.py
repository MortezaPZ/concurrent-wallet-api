from __future__ import annotations

from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from . import services
from .models import Transaction, Wallet
from .serializers import (
    DebitRequestSerializer,
    DebitResponseSerializer,
    TransactionSerializer,
    WalletSerializer,
)

UUID_REGEX = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

ERROR_RESPONSES = {
    400: OpenApiResponse(description="Invalid payload."),
    404: OpenApiResponse(description="Wallet not found."),
    409: OpenApiResponse(description="request_id reused with a different amount."),
    422: OpenApiResponse(description="Insufficient funds."),
}


class WalletViewSet(viewsets.ReadOnlyModelViewSet):
    """Read the wallet, read its ledger, and debit it idempotently."""

    queryset = Wallet.objects.all()
    serializer_class = WalletSerializer
    lookup_value_regex = UUID_REGEX

    @extend_schema(
        summary="List the transactions of a wallet, newest first.",
        responses=TransactionSerializer(many=True),
    )
    @action(detail=True, methods=["get"])
    def transactions(self, request: Request, pk: str | None = None) -> Response:
        wallet = self.get_object()
        queryset = wallet.transactions.all()
        page = self.paginate_queryset(queryset)
        serializer = TransactionSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @extend_schema(
        summary="Debit the wallet exactly once per request_id.",
        request=DebitRequestSerializer,
        responses={
            201: OpenApiResponse(DebitResponseSerializer, description="Debit applied."),
            200: OpenApiResponse(
                DebitResponseSerializer,
                description="Idempotent replay; balance unchanged.",
            ),
            **ERROR_RESPONSES,
        },
    )
    @action(detail=True, methods=["post"])
    def debit(self, request: Request, pk: str | None = None) -> Response:
        payload = DebitRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        outcome = services.debit(
            wallet_id=UUID(pk),
            amount=payload.validated_data["amount"],
            request_id=payload.validated_data["request_id"],
        )

        body = DebitResponseSerializer(
            {
                "replayed": outcome.replayed,
                "balance": outcome.transaction.balance_after,
                "transaction": outcome.transaction,
            }
        ).data
        http_status = status.HTTP_200_OK if outcome.replayed else status.HTTP_201_CREATED
        headers = {"Idempotent-Replay": "true"} if outcome.replayed else {}
        return Response(body, status=http_status, headers=headers)


class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """Append-only ledger. Write methods are not routed at all."""

    queryset = Transaction.objects.all()
    serializer_class = TransactionSerializer
    lookup_value_regex = UUID_REGEX

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "wallet",
                str,
                description="Filter the ledger by wallet id.",
            )
        ]
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        wallet_id = self.request.query_params.get("wallet")
        if not wallet_id:
            return queryset
        try:
            return queryset.filter(wallet_id=UUID(wallet_id))
        except ValueError as exc:
            raise ValidationError({"wallet": "Must be a valid UUID."}) from exc
