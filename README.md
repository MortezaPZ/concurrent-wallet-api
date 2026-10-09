# Concurrent Wallet API

Debit a wallet exactly once per `request_id`, even when two requests arrive at the same time. The guarantee lives in PostgreSQL, not in a Python lock.

Django 5.2, Django REST Framework 3.18, PostgreSQL 14 or 16, psycopg 3, Python 3.11 through 3.13.

## Overview

A small wallet service. Each debit locks the wallet row, checks the balance, writes the ledger line, and commits. Replaying the same request returns the original result and does not debit again.

## Features

- Row lock with `SELECT ... FOR UPDATE` under `READ COMMITTED`
- Idempotency enforced by `UNIQUE (wallet_id, request_id)`
- Money stored as `Decimal(18, 2)`, never float
- Append-only ledger: no update or delete route, model guards, and a PostgreSQL trigger
- Balance, amount, and `balance_after` are `CHECK` constraints
- A demo wallet is created by the migrations with balance `100.00`

## Technology Stack

- Python 3.11+
- Django 5.2 and Django REST Framework
- PostgreSQL
- pytest

## Architecture

Every debit runs inside one database transaction. The service locks the wallet row before it reads the balance, so two concurrent debits of 80 from a balance of 100 cannot both succeed. The loser waits, reads the remaining balance, and returns `insufficient_funds`.

Idempotency is a unique constraint, not a cache. A replay with the same amount returns `200`. A replay with a different amount returns `409`. A rejected debit does not consume the request id.

The ledger needs a total order. Timestamps collide, so each row takes a PostgreSQL sequence number. Authentication, payments, and a user interface are out of scope. `django.contrib.auth`, sessions, and admin are not installed.

## Installation

```bash
cp .env.example .env
docker compose up -d --wait postgres
python -m venv .venv
```

Windows:

```powershell
.\.venv\Scripts\activate
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py runserver
```

Linux or macOS: `source .venv/bin/activate` instead of the Windows activate script. Point `.env` at an existing PostgreSQL instance if you are not using Compose.

After migrate, wallet `00000000-0000-0000-0000-000000000001` has balance `100.00`. Interactive docs: `http://127.0.0.1:8000/api/docs/`.

## Usage

```bash
W=00000000-0000-0000-0000-000000000001

curl -s localhost:8000/api/wallets/$W/
curl -s -X POST localhost:8000/api/wallets/$W/debit/ \
     -H 'Content-Type: application/json' \
     -d '{"amount": "80.00", "request_id": "order-1"}'
curl -s localhost:8000/api/wallets/$W/transactions/
```

| Method | Path | Result |
| --- | --- | --- |
| `GET` | `/api/wallets/{id}/` | Balance |
| `GET` | `/api/wallets/{id}/transactions/` | That wallet's transactions, newest first |
| `POST` | `/api/wallets/{id}/debit/` | Debit with `{"amount", "request_id"}` |
| `GET` | `/api/transactions/{id}/` | One transaction |

| Status | Meaning |
| --- | --- |
| `201` | Debit applied |
| `200` | Same `request_id` and amount; nothing is debited again |
| `400` | Invalid input |
| `404` | Wallet not found |
| `409` | Same `request_id` with a different amount |
| `422` | Insufficient balance |

## Testing

```bash
pytest -v
pytest -v -m concurrency
```

The suite runs only on PostgreSQL. There is no SQLite fallback, because `SELECT ... FOR UPDATE` does not provide the same lock there. Concurrency tests open real parallel connections. One scenario drives the race through live HTTP requests.

CI runs Python 3.11, 3.12, and 3.13 against PostgreSQL 16, plus one job on PostgreSQL 14.

| Behavior | Test module |
| --- | --- |
| Balance, transactions, and debit API | `tests/test_api.py` |
| Balance cannot go negative | `tests/test_negative_balance.py` |
| Replay does not debit twice | `tests/test_idempotency.py` |
| Same request id with a different amount is rejected | `tests/test_idempotency.py` |
| Two simultaneous debits of 80, exactly one succeeds | `tests/test_concurrency.py` |
| A recorded transaction cannot be edited or deleted | `tests/test_immutability.py` |

## Limitations

No authentication, payment gateway, admin, or deployment story. Environment variables are listed in `.env.example`. No secret belongs in the repository.

## License

See the repository license file if one is present.
