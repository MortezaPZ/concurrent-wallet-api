"""Requirement 7: a recorded transaction can never be edited or deleted."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.urls import reverse

from tests.conftest import debit_payload
from wallets.models import ImmutableTransactionError, Transaction

pytestmark = pytest.mark.django_db


@pytest.fixture
def recorded(api, wallet, debit_url) -> Transaction:
    api.post(debit_url, debit_payload("30.00", "req-immutable"))
    return Transaction.objects.get(request_id="req-immutable")


@pytest.mark.parametrize("method", ["put", "patch", "delete", "post"])
def test_transaction_endpoints_reject_write_methods(api, recorded, method):
    url = reverse("transaction-detail", args=[recorded.id])

    response = getattr(api, method)(url, {"amount": "1.00"})

    assert response.status_code == 405
    recorded.refresh_from_db()
    assert recorded.amount == Decimal("30.00")


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_transaction_collection_rejects_write_methods(api, recorded, method):
    assert getattr(api, method)(reverse("transaction-list")).status_code == 405


@pytest.mark.parametrize("method", ["put", "patch", "delete", "post"])
def test_wallet_endpoints_reject_write_methods(api, wallet, method):
    url = reverse("wallet-detail", args=[wallet.id])

    assert getattr(api, method)(url, {"balance": "999.00"}).status_code == 405


def test_transaction_still_readable_after_write_attempts(api, recorded):
    response = api.get(reverse("transaction-detail", args=[recorded.id]))

    assert response.status_code == 200
    assert response.json()["amount"] == "30.00"


def test_model_layer_refuses_to_save_an_existing_transaction(recorded):
    recorded.amount = Decimal("1.00")

    with pytest.raises(ImmutableTransactionError):
        recorded.save()


def test_model_layer_refuses_to_delete_a_transaction(recorded):
    with pytest.raises(ImmutableTransactionError):
        recorded.delete()


def test_database_trigger_blocks_a_queryset_update(recorded):
    with pytest.raises(IntegrityError, match="append-only"), transaction.atomic():
        Transaction.objects.filter(pk=recorded.pk).update(amount=Decimal("1.00"))


def test_database_trigger_blocks_a_queryset_delete(recorded):
    with pytest.raises(IntegrityError, match="append-only"), transaction.atomic():
        Transaction.objects.filter(pk=recorded.pk).delete()


def test_database_trigger_blocks_raw_sql(recorded):
    with (
        pytest.raises(IntegrityError, match="append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("DELETE FROM wallet_transaction WHERE id = %s", [recorded.pk])


def test_wallet_with_history_cannot_be_deleted(recorded, wallet):
    with pytest.raises(ProtectedError), transaction.atomic():
        wallet.delete()
