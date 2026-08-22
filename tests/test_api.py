"""Requirement 1 and 2: read balance and ledger, debit with amount + request_id."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.management import call_command
from django.urls import reverse

from tests.conftest import debit_payload
from wallets.models import INITIAL_BALANCE, Transaction, Wallet
from wallets.seed import DEMO_WALLET_ID, ensure_demo_wallet

pytestmark = pytest.mark.django_db


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_wallet_starts_with_one_hundred_units(api, wallet):
    response = api.get(reverse("wallet-detail", args=[wallet.id]))

    assert response.status_code == 200
    assert response.json()["balance"] == "100.00"
    assert response.json()["id"] == str(wallet.id)


def test_demo_wallet_seeding_starts_at_one_hundred_and_is_idempotent(db):
    Wallet.objects.filter(pk=DEMO_WALLET_ID).delete()

    first = ensure_demo_wallet()
    assert first.balance == INITIAL_BALANCE

    first.balance = Decimal("42.00")
    first.save(update_fields=["balance"])
    second = ensure_demo_wallet()

    assert first.pk == second.pk == DEMO_WALLET_ID
    assert Wallet.objects.filter(pk=DEMO_WALLET_ID).count() == 1
    assert second.balance == Decimal("42.00")


def test_seed_command_reports_the_wallet(db, capsys):
    call_command("seed_wallet")

    assert str(DEMO_WALLET_ID) in capsys.readouterr().out


def test_debit_reduces_balance_and_records_a_transaction(api, wallet, debit_url):
    response = api.post(debit_url, debit_payload("30.00", "req-1"))

    assert response.status_code == 201
    body = response.json()
    assert body["replayed"] is False
    assert body["balance"] == "70.00"
    assert body["transaction"]["amount"] == "30.00"
    assert body["transaction"]["kind"] == "DEBIT"
    assert body["transaction"]["request_id"] == "req-1"
    assert body["transaction"]["balance_after"] == "70.00"

    wallet.refresh_from_db()
    assert wallet.balance == Decimal("70.00")
    assert wallet.transactions.count() == 1


def test_debit_may_empty_the_wallet_exactly(api, wallet, debit_url):
    response = api.post(debit_url, debit_payload("100.00", "req-all"))

    assert response.status_code == 201
    wallet.refresh_from_db()
    assert wallet.balance == Decimal("0.00")


def test_transactions_endpoint_lists_newest_first(api, wallet, debit_url):
    api.post(debit_url, debit_payload("10.00", "req-a"))
    api.post(debit_url, debit_payload("20.00", "req-b"))

    response = api.get(reverse("wallet-transactions", args=[wallet.id]))

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert [row["request_id"] for row in body["results"]] == ["req-b", "req-a"]
    assert [row["balance_after"] for row in body["results"]] == ["70.00", "90.00"]


def test_ledger_order_survives_identical_timestamps(api, wallet, debit_url):
    """Entries written inside one clock tick must still come back in order."""
    written = [f"tick-{index:02d}" for index in range(12)]
    for request_id in written:
        api.post(debit_url, debit_payload("1.00", request_id))

    response = api.get(reverse("wallet-transactions", args=[wallet.id]))
    returned = [row["request_id"] for row in response.json()["results"]]

    assert returned == list(reversed(written))

    sequences = list(
        Transaction.objects.filter(wallet=wallet)
        .order_by("sequence")
        .values_list("sequence", flat=True)
    )
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(written)


def test_transaction_list_can_be_filtered_by_wallet(api, wallet, other_wallet, debit_url):
    api.post(debit_url, debit_payload("10.00", "req-a"))
    api.post(reverse("wallet-debit", args=[other_wallet.id]), debit_payload("5.00", "req-a"))

    response = api.get(reverse("transaction-list"), {"wallet": str(wallet.id)})

    assert response.status_code == 200
    assert [row["amount"] for row in response.json()["results"]] == ["10.00"]


def test_debit_on_unknown_wallet_returns_404(api, db):
    url = reverse("wallet-debit", args=["11111111-1111-1111-1111-111111111111"])

    response = api.post(url, debit_payload("1.00", "req-x"))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "wallet_not_found"


def test_malformed_wallet_id_is_not_routed(api, db):
    assert api.get("/api/wallets/not-a-uuid/").status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"amount": "0.00", "request_id": "r"}, id="zero"),
        pytest.param({"amount": "-5.00", "request_id": "r"}, id="negative"),
        pytest.param({"amount": "1.005", "request_id": "r"}, id="too-many-decimals"),
        pytest.param({"amount": "abc", "request_id": "r"}, id="not-a-number"),
        pytest.param({"amount": "1.00"}, id="missing-request-id"),
        pytest.param({"request_id": "r"}, id="missing-amount"),
        pytest.param({"amount": "1.00", "request_id": ""}, id="empty-request-id"),
        pytest.param({"amount": "1.00", "request_id": "x" * 65}, id="request-id-too-long"),
        pytest.param({"amount": "1.00", "request_id": "bad id!"}, id="illegal-characters"),
    ],
)
def test_debit_rejects_invalid_payloads(api, wallet, debit_url, payload):
    response = api.post(debit_url, payload)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"

    wallet.refresh_from_db()
    assert wallet.balance == INITIAL_BALANCE
    assert not Transaction.objects.exists()
