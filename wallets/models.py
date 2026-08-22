from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Func, Value

MONEY = {
    "max_digits": settings.WALLET_MAX_DIGITS,
    "decimal_places": settings.WALLET_DECIMAL_PLACES,
}

INITIAL_BALANCE = Decimal("100.00")

LEDGER_SEQUENCE = "wallet_transaction_sequence"


class ImmutableTransactionError(RuntimeError):
    """Raised when code tries to mutate or delete a recorded transaction."""


class Wallet(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    balance = models.DecimalField(
        **MONEY,
        default=INITIAL_BALANCE,
        validators=[MinValueValidator(Decimal("0"))],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wallet"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(balance__gte=Decimal("0")),
                name="wallet_balance_non_negative",
            )
        ]

    def __str__(self) -> str:
        return f"Wallet({self.id}, balance={self.balance})"


class TransactionKind(models.TextChoices):
    DEBIT = "DEBIT", "Debit"


class Transaction(models.Model):
    """An append-only ledger entry. Never updated, never deleted."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # A ledger needs a total order. Timestamps cannot provide one: clock
    # resolution ties are real (~15ms on Windows), and a random UUID is no
    # tie-breaker. A database sequence orders entries by insertion, and the
    # wallet row lock makes that the commit order too.
    sequence = models.BigIntegerField(
        editable=False,
        unique=True,
        db_default=Func(Value(LEDGER_SEQUENCE), function="nextval"),
    )
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="transactions")
    request_id = models.CharField(max_length=64)
    kind = models.CharField(
        max_length=16, choices=TransactionKind.choices, default=TransactionKind.DEBIT
    )
    amount = models.DecimalField(**MONEY)
    balance_after = models.DecimalField(**MONEY)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wallet_transaction"
        ordering = ["-sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["wallet", "request_id"],
                name="wallet_transaction_idempotency_key",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=Decimal("0")),
                name="wallet_transaction_amount_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(balance_after__gte=Decimal("0")),
                name="wallet_transaction_balance_after_non_negative",
            ),
        ]
        indexes = [models.Index(fields=["wallet", "-sequence"])]

    def __str__(self) -> str:
        return f"{self.kind} {self.amount} ({self.request_id})"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableTransactionError("Transactions are append-only and cannot be modified.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableTransactionError("Transactions are append-only and cannot be deleted.")
