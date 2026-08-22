"""Enforce ledger immutability in the database, below every application layer."""

from django.db import migrations

CREATE_GUARD = """
CREATE OR REPLACE FUNCTION wallet_transaction_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'wallet_transaction rows are append-only (attempted %)', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER wallet_transaction_append_only
BEFORE UPDATE OR DELETE ON wallet_transaction
FOR EACH ROW EXECUTE FUNCTION wallet_transaction_append_only();
"""

DROP_GUARD = """
DROP TRIGGER IF EXISTS wallet_transaction_append_only ON wallet_transaction;
DROP FUNCTION IF EXISTS wallet_transaction_append_only();
"""


class Migration(migrations.Migration):
    dependencies = [("wallets", "0001_initial")]

    operations = [migrations.RunSQL(sql=CREATE_GUARD, reverse_sql=DROP_GUARD)]
