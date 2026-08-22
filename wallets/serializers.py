from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.validators import RegexValidator
from rest_framework import serializers

from .models import Transaction, Wallet

MONEY = {
    "max_digits": settings.WALLET_MAX_DIGITS,
    "decimal_places": settings.WALLET_DECIMAL_PLACES,
}

REQUEST_ID_VALIDATOR = RegexValidator(
    regex=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$",
    message=(
        "request_id must be 1-64 characters of letters, digits, dot, dash, "
        "underscore or colon, and must start with a letter or digit."
    ),
)


class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = ["id", "balance", "created_at", "updated_at"]
        read_only_fields = fields


class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = [
            "id",
            "wallet",
            "request_id",
            "kind",
            "amount",
            "balance_after",
            "created_at",
        ]
        read_only_fields = fields


class DebitRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        **MONEY,
        min_value=Decimal("0.01"),
        help_text="Positive amount to debit, at most 2 decimal places.",
    )
    request_id = serializers.CharField(
        max_length=64,
        validators=[REQUEST_ID_VALIDATOR],
        help_text="Idempotency key. Replaying it never debits twice.",
    )


class DebitResponseSerializer(serializers.Serializer):
    replayed = serializers.BooleanField(
        help_text="True when the request_id was already applied earlier."
    )
    balance = serializers.DecimalField(**MONEY, help_text="Wallet balance after the debit.")
    transaction = TransactionSerializer()
