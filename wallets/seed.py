"""Creation of the demo wallet, shared by the data migration and the CLI."""

from __future__ import annotations

from uuid import UUID

DEMO_WALLET_ID = UUID("00000000-0000-0000-0000-000000000001")


def ensure_demo_wallet(wallet_model=None):
    """Create the demo wallet if missing. Never touches an existing balance."""
    if wallet_model is None:
        from .models import Wallet as wallet_model

    wallet, _created = wallet_model.objects.get_or_create(pk=DEMO_WALLET_ID)
    return wallet
