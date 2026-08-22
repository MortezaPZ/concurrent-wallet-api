"""Transactional wallet operations.

Correctness model
-----------------
Every debit runs inside one database transaction that starts by taking a
``SELECT ... FOR UPDATE`` row lock on the wallet. That single lock makes the
read-check-write sequence atomic against any number of concurrent workers, so
"read balance -> decide -> write balance" can never interleave.

The unique constraint on ``(wallet, request_id)`` is the second line of
defence: even if a debit somehow escaped the lock, the database would still
refuse the duplicate ledger row.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction

from .exceptions import (
    IdempotencyKeyConflictError,
    InsufficientFundsError,
    WalletNotFoundError,
)
from .models import Transaction, TransactionKind, Wallet

logger = logging.getLogger(__name__)

QUANTUM = Decimal(1).scaleb(-settings.WALLET_DECIMAL_PLACES)


@dataclass(frozen=True)
class DebitOutcome:
    """Result of a debit attempt: the ledger row, and whether it is a replay."""

    transaction: Transaction
    replayed: bool


def quantize_money(amount: Decimal) -> Decimal:
    return Decimal(amount).quantize(QUANTUM, rounding=ROUND_HALF_UP)


def get_wallet(wallet_id: UUID) -> Wallet:
    try:
        return Wallet.objects.get(pk=wallet_id)
    except Wallet.DoesNotExist as exc:
        raise WalletNotFoundError() from exc


def debit(*, wallet_id: UUID, amount: Decimal, request_id: str) -> DebitOutcome:
    """Debit ``amount`` from a wallet exactly once per ``request_id``."""
    amount = quantize_money(amount)

    with transaction.atomic():
        wallet = _lock_wallet(wallet_id)

        replay = _find_by_request_id(wallet, request_id)
        if replay is not None:
            _reject_amount_mismatch(replay, amount)
            logger.info(
                "debit replayed wallet=%s request_id=%s amount=%s",
                wallet.pk,
                request_id,
                amount,
            )
            return DebitOutcome(transaction=replay, replayed=True)

        if wallet.balance < amount:
            raise InsufficientFundsError(balance=wallet.balance, requested=amount)

        new_balance = wallet.balance - amount
        try:
            with transaction.atomic():
                ledger_entry = Transaction.objects.create(
                    wallet=wallet,
                    request_id=request_id,
                    kind=TransactionKind.DEBIT,
                    amount=amount,
                    balance_after=new_balance,
                )
        except IntegrityError:
            # Unreachable while the row lock holds; kept because the unique
            # constraint - not the lock - is the authoritative guarantee.
            replay = _find_by_request_id(wallet, request_id)
            if replay is None:
                raise
            _reject_amount_mismatch(replay, amount)
            return DebitOutcome(transaction=replay, replayed=True)

        wallet.balance = new_balance
        wallet.save(update_fields=["balance", "updated_at"])

        logger.info(
            "debit applied wallet=%s request_id=%s amount=%s balance_after=%s",
            wallet.pk,
            request_id,
            amount,
            new_balance,
        )
        return DebitOutcome(transaction=ledger_entry, replayed=False)


def _lock_wallet(wallet_id: UUID) -> Wallet:
    try:
        return Wallet.objects.select_for_update().get(pk=wallet_id)
    except Wallet.DoesNotExist as exc:
        raise WalletNotFoundError() from exc


def _find_by_request_id(wallet: Wallet, request_id: str) -> Transaction | None:
    return wallet.transactions.filter(request_id=request_id).first()


def _reject_amount_mismatch(existing: Transaction, amount: Decimal) -> None:
    if existing.amount != amount:
        raise IdempotencyKeyConflictError(
            request_id=existing.request_id,
            existing_amount=existing.amount,
            requested_amount=amount,
        )
