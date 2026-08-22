from django.core.management.base import BaseCommand

from wallets.seed import ensure_demo_wallet


class Command(BaseCommand):
    help = "Create the demo wallet if it does not exist yet."

    def handle(self, *args, **options) -> None:
        wallet = ensure_demo_wallet()
        self.stdout.write(f"wallet {wallet.pk} balance {wallet.balance}")
