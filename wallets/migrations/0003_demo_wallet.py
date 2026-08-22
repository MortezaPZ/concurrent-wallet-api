"""Ship a ready-to-use wallet so `migrate` is the only setup step."""

from django.db import migrations

from wallets.seed import DEMO_WALLET_ID, ensure_demo_wallet


def create_demo_wallet(apps, _schema_editor):
    ensure_demo_wallet(apps.get_model("wallets", "Wallet"))


def remove_demo_wallet(apps, _schema_editor):
    apps.get_model("wallets", "Wallet").objects.filter(pk=DEMO_WALLET_ID).delete()


class Migration(migrations.Migration):
    dependencies = [("wallets", "0002_transaction_append_only")]

    operations = [migrations.RunPython(create_demo_wallet, remove_demo_wallet)]
