"""Requirements 4 and 5: replaying a request_id, and reusing it with another amount."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from tests.conftest import debit_payload
from wallets.models import INITIAL_BALANCE, Transaction

pytestmark = pytest.mark.django_db


def test_replaying_the_same_request_id_never_debits_twice(api, wallet, debit_url):
    first = api.post(debit_url, debit_payload("30.00", "req-dup"))
    second = api.post(debit_url, debit_payload("30.00", "req-dup"))

    assert first.status_code == 201
    assert first.json()["replayed"] is False

    assert second.status_code == 200
    assert second.json()["replayed"] is True
    assert second.headers["Idempotent-Replay"] == "true"
    assert second.json()["transaction"] == first.json()["transaction"]

    wallet.refresh_from_db()
    assert wallet.balance == Decimal("70.00")
    assert wallet.transactions.count() == 1


def test_replaying_many_times_is_still_a_single_debit(api, wallet, debit_url):
    statuses = [
        api.post(debit_url, debit_payload("25.00", "req-retry")).status_code for _ in range(6)
    ]

    assert statuses == [201, 200, 200, 200, 200, 200]
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("75.00")
    assert wallet.transactions.count() == 1


def test_replay_works_even_when_the_balance_would_no_longer_allow_it(api, wallet, debit_url):
    api.post(debit_url, debit_payload("60.00", "req-first"))
    api.post(debit_url, debit_payload("40.00", "req-second"))

    replay = api.post(debit_url, debit_payload("60.00", "req-first"))

    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("0.00")
    assert wallet.transactions.count() == 2


def test_reusing_a_request_id_with_a_different_amount_is_rejected(api, wallet, debit_url):
    api.post(debit_url, debit_payload("30.00", "req-conflict"))

    response = api.post(debit_url, debit_payload("31.00", "req-conflict"))

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "idempotency_key_conflict"
    assert error["details"] == {
        "request_id": "req-conflict",
        "existing_amount": "30.00",
        "requested_amount": "31.00",
    }

    wallet.refresh_from_db()
    assert wallet.balance == Decimal("70.00")
    assert wallet.transactions.count() == 1


def test_conflicting_replay_is_rejected_even_for_a_smaller_amount(api, wallet, debit_url):
    api.post(debit_url, debit_payload("30.00", "req-conflict"))

    response = api.post(debit_url, debit_payload("1.00", "req-conflict"))

    assert response.status_code == 409
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("70.00")


def test_request_ids_are_scoped_to_their_own_wallet(api, wallet, other_wallet, debit_url):
    first = api.post(debit_url, debit_payload("10.00", "shared-key"))
    second = api.post(
        reverse("wallet-debit", args=[other_wallet.id]),
        debit_payload("20.00", "shared-key"),
    )

    assert (first.status_code, second.status_code) == (201, 201)
    wallet.refresh_from_db()
    other_wallet.refresh_from_db()
    assert wallet.balance == Decimal("90.00")
    assert other_wallet.balance == Decimal("80.00")
    assert Transaction.objects.filter(request_id="shared-key").count() == 2


def test_a_rejected_debit_leaves_the_request_id_free_to_reuse(api, wallet, debit_url):
    rejected = api.post(debit_url, debit_payload("500.00", "req-reuse"))
    accepted = api.post(debit_url, debit_payload("10.00", "req-reuse"))

    assert rejected.status_code == 422
    assert accepted.status_code == 201
    wallet.refresh_from_db()
    assert wallet.balance == INITIAL_BALANCE - Decimal("10.00")
