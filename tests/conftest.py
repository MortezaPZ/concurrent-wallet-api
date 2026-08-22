from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from wallets.models import Wallet


@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.fixture
def wallet(db) -> Wallet:
    return Wallet.objects.create()


@pytest.fixture
def other_wallet(db) -> Wallet:
    return Wallet.objects.create()


@pytest.fixture
def debit_url(wallet: Wallet) -> str:
    return reverse("wallet-debit", args=[wallet.id])


def debit_payload(amount: str, request_id: str) -> dict[str, str]:
    return {"amount": amount, "request_id": request_id}
