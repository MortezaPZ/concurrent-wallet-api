"""Requirement 6: two simultaneous debits of 80 - exactly one wins.

These tests open real parallel database sessions, so they only mean anything on
PostgreSQL. ``transaction=True`` is mandatory: the threads must see committed
data, which rules out the single shared transaction that normal tests run in.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any

import pytest
from django.db import connection, connections
from django.test.utils import CaptureQueriesContext

from wallets.exceptions import InsufficientFundsError, WalletError
from wallets.models import INITIAL_BALANCE, Transaction, Wallet
from wallets.services import DebitOutcome, debit

pytestmark = pytest.mark.concurrency

TIMEOUT = 30


def _run_in_parallel(worker: Callable[[int], Any], count: int) -> list[Any]:
    """Release ``count`` workers at the same instant and collect their results."""
    barrier = threading.Barrier(count)

    def wrapped(index: int) -> Any:
        barrier.wait(timeout=TIMEOUT)
        try:
            return worker(index)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = [pool.submit(wrapped, index) for index in range(count)]
        return [future.result(timeout=TIMEOUT) for future in futures]


def _try_debit(wallet_id, amount: str, request_id: str) -> DebitOutcome | WalletError:
    try:
        return debit(wallet_id=wallet_id, amount=Decimal(amount), request_id=request_id)
    except WalletError as exc:
        return exc


def test_the_test_database_is_postgresql(db):
    assert connection.vendor == "postgresql", (
        "The concurrency guarantees of this service depend on PostgreSQL row locks."
    )


@pytest.mark.django_db
def test_debit_locks_the_wallet_row(wallet):
    with CaptureQueriesContext(connection) as queries:
        debit(wallet_id=wallet.id, amount=Decimal("1.00"), request_id="lock-check")

    assert any("FOR UPDATE" in entry["sql"].upper() for entry in queries.captured_queries)


@pytest.mark.django_db(transaction=True)
def test_two_simultaneous_debits_of_eighty_leave_exactly_one_winner():
    wallet = Wallet.objects.create()
    assert wallet.balance == INITIAL_BALANCE == Decimal("100.00")

    results = _run_in_parallel(
        lambda index: _try_debit(wallet.id, "80.00", f"race-{index}"), count=2
    )

    applied = [item for item in results if isinstance(item, DebitOutcome)]
    refused = [item for item in results if isinstance(item, InsufficientFundsError)]

    assert len(applied) == 1, f"expected exactly one winner, got {results}"
    assert len(refused) == 1, f"expected exactly one rejection, got {results}"
    assert applied[0].transaction.balance_after == Decimal("20.00")

    wallet.refresh_from_db()
    assert wallet.balance == Decimal("20.00")
    assert Transaction.objects.filter(wallet=wallet).count() == 1


@pytest.mark.django_db(transaction=True)
def test_a_crowd_of_debits_can_never_oversell_the_balance():
    wallet = Wallet.objects.create()
    assert wallet.balance == Decimal("100.00")

    results = _run_in_parallel(
        lambda index: _try_debit(wallet.id, "20.00", f"crowd-{index}"), count=12
    )

    applied = [item for item in results if isinstance(item, DebitOutcome)]
    refused = [item for item in results if isinstance(item, InsufficientFundsError)]

    assert len(applied) == 5
    assert len(refused) == 7

    wallet.refresh_from_db()
    assert wallet.balance == Decimal("0.00")
    assert Transaction.objects.filter(wallet=wallet).count() == 5
    assert sorted(item.transaction.balance_after for item in applied) == [
        Decimal("0.00"),
        Decimal("20.00"),
        Decimal("40.00"),
        Decimal("60.00"),
        Decimal("80.00"),
    ]


@pytest.mark.django_db(transaction=True)
def test_the_same_request_id_sent_simultaneously_debits_only_once():
    wallet = Wallet.objects.create()
    assert wallet.balance == Decimal("100.00")

    results = _run_in_parallel(lambda _index: _try_debit(wallet.id, "80.00", "same-key"), count=8)

    assert all(isinstance(item, DebitOutcome) for item in results)
    assert len([item for item in results if not item.replayed]) == 1
    assert len({item.transaction.pk for item in results}) == 1

    wallet.refresh_from_db()
    assert wallet.balance == Decimal("20.00")
    assert Transaction.objects.filter(wallet=wallet).count() == 1


@pytest.mark.django_db(transaction=True)
def test_simultaneous_debits_over_http_behave_the_same(live_server):
    wallet = Wallet.objects.create()
    assert wallet.balance == Decimal("100.00")
    url = f"{live_server.url}/api/wallets/{wallet.id}/debit/"

    def call(index: int) -> tuple[int, dict]:
        request = urllib.request.Request(
            url,
            data=json.dumps({"amount": "80.00", "request_id": f"http-{index}"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    results = _run_in_parallel(call, count=2)

    assert sorted(status for status, _ in results) == [201, 422]
    rejected = next(body for status, body in results if status == 422)
    assert rejected["error"]["code"] == "insufficient_funds"

    wallet.refresh_from_db()
    assert wallet.balance == Decimal("20.00")
    assert Transaction.objects.filter(wallet=wallet).count() == 1
