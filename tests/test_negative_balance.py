"""Requirement 3: the balance can never go negative."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from tests.conftest import debit_payload
from wallets.models import INITIAL_BALANCE, Transaction, Wallet

pytestmark = pytest.mark.django_db


def test_debit_larger_than_balance_is_rejected(api, wallet, debit_url):
    response = api.post(debit_url, debit_payload("100.01", "req-too-big"))

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "insufficient_funds"
    assert error["details"] == {
        "balance": "100.00",
        "requested": "100.01",
        "shortfall": "0.01",
    }

    wallet.refresh_from_db()
    assert wallet.balance == INITIAL_BALANCE
    assert not Transaction.objects.exists()


def test_balance_cannot_be_drained_by_repeated_debits(api, wallet, debit_url):
    for index in range(5):
        assert api.post(debit_url, debit_payload("20.00", f"req-{index}")).status_code == 201

    assert api.post(debit_url, debit_payload("0.01", "req-last")).status_code == 422

    wallet.refresh_from_db()
    assert wallet.balance == Decimal("0.00")


def test_database_refuses_a_negative_balance_even_from_raw_writes(wallet):
    with pytest.raises(IntegrityError), transaction.atomic():
        Wallet.objects.filter(pk=wallet.pk).update(balance=Decimal("-0.01"))
