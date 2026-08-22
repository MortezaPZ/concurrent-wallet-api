# Concurrent Wallet Operation

[![CI](https://github.com/MortezaPZ/concurrent-wallet-api/actions/workflows/ci.yml/badge.svg)](https://github.com/MortezaPZ/concurrent-wallet-api/actions/workflows/ci.yml)

سرویس کوچکی با Django REST Framework که از یک کیف پول کسر می‌کند، به‌صورت امن در برابر هم‌زمانی و دقیقاً یک بار به ازای هر `request_id`. تضمین درستی در خود دیتابیس است: قفل سطری `SELECT ... FOR UPDATE`، کلید یکتای idempotency، قیدهای `CHECK` و یک تریگر append-only.

Django 5.2 · DRF 3.18 · PostgreSQL 14/16 · psycopg 3 · Python 3.11 تا 3.13

## اجرا

```bash
cp .env.example .env
docker compose up -d --wait postgres        # یا .env را به پستگرس خودتان وصل کنید
python -m venv .venv && . .venv/bin/activate   # ویندوز: .venv\Scripts\activate
pip install -r requirements-dev.txt
python manage.py migrate                    # کیف پول نمونه با موجودی ۱۰۰ هم ساخته می‌شود
python manage.py runserver
```

پس از `migrate` یک کیف پول با شناسه `00000000-0000-0000-0000-000000000001` و موجودی `100.00` وجود دارد. مستندات تعاملی: <http://127.0.0.1:8000/api/docs/>

```bash
W=00000000-0000-0000-0000-000000000001

curl -s localhost:8000/api/wallets/$W/
curl -s -X POST localhost:8000/api/wallets/$W/debit/ \
     -H 'Content-Type: application/json' \
     -d '{"amount": "80.00", "request_id": "order-1"}'
curl -s localhost:8000/api/wallets/$W/transactions/
```

## تست

```bash
pytest -v                 # کل سوئیت
pytest -v -m concurrency  # فقط سناریوهای هم‌زمانی
```

تست‌ها **فقط روی PostgreSQL** اجرا می‌شوند؛ هیچ fallback ای به SQLite در تنظیمات وجود ندارد، چون `SELECT ... FOR UPDATE` روی SQLite بی‌اثر است و تمام تضمین‌های هم‌زمانی بی‌سروصدا تست‌نشده باقی می‌مانند. تست‌های هم‌زمانی کانکشن‌های موازی واقعی باز می‌کنند و یکی از سناریوها ریس را از طریق درخواست‌های HTTP واقعی روی یک سرور زنده اجرا می‌کند.

CI روی پایتون ۳.۱۱ و ۳.۱۲ و ۳.۱۳ با PostgreSQL 16، به‌علاوه PostgreSQL 14 اجرا می‌شود.

## API

| متد | مسیر | نتیجه |
| --- | --- | --- |
| `GET` | `/api/wallets/{id}/` | موجودی |
| `GET` | `/api/wallets/{id}/transactions/` | تراکنش‌های همان کیف پول، جدیدترین اول |
| `POST` | `/api/wallets/{id}/debit/` | کسر با `{"amount", "request_id"}` |
| `GET` | `/api/transactions/{id}/` | یک تراکنش |

پاسخ‌های `debit`:

| کد | معنی |
| --- | --- |
| `201` | کسر انجام شد |
| `200` | همان `request_id` با همان مبلغ دوباره ارسال شده؛ **چیزی دوباره کسر نمی‌شود** |
| `400` | ورودی نامعتبر |
| `404` | کیف پول یافت نشد |
| `409` | همان `request_id` با مبلغ متفاوت |
| `422` | موجودی کافی نیست |

قالب خطاها یکسان است:

```json
{"error": {"code": "insufficient_funds",
           "message": "Balance is not sufficient for this debit.",
           "details": {"balance": "20.00", "requested": "80.00", "shortfall": "60.00"}}}
```

## تصمیم‌های فنی

**قفل بدبینانه روی ردیف، نه منطق در پایتون.** هر کسر داخل یک تراکنش دیتابیس شروع می‌شود و اول `SELECT ... FOR UPDATE` روی ردیف کیف پول می‌گیرد، بعد موجودی را می‌خواند، تصمیم می‌گیرد، می‌نویسد و ردیف دفتر را ثبت می‌کند. این قفل، دنباله «خواندن ← بررسی ← نوشتن» را اتمیک می‌کند، پس دو درخواست هم‌زمان نمی‌توانند هر دو موجودی ۱۰۰ را ببینند و هر دو ۸۰ کسر کنند. بازنده منتظر می‌ماند، بعد موجودی ۲۰ را می‌خواند و با `insufficient_funds` رد می‌شود. به همین دلیل نتیجه قطعی است، نه «معمولاً درست».

جایگزین‌ها بررسی شدند: `F("balance") - amount` نوشتن را اتمیک می‌کند ولی خودِ تصمیمِ «آیا کافی است؟» همچنان ریس دارد؛ قفل خوش‌بینانه نیاز به retry سمت کلاینت دارد و رد شدنِ قطعی را احتمالی می‌کند؛ ایزولیشن `SERIALIZABLE` درست است اما خطای serialization را به همه فراخوان‌ها تحمیل می‌کند، در حالی که `READ COMMITTED` به‌علاوه قفل صریح چیزی برای retry باقی نمی‌گذارد.

**Idempotency یک قید دیتابیسی است، نه کش.** ضمانت واقعی `UNIQUE (wallet_id, request_id)` است؛ جست‌وجوی داخل تراکنش فقط برای این است که تکرار یک `200` تمیز بگیرد به جای `IntegrityError`. کلید به ازای هر کیف پول scope شده است. تکرار با مبلغ متفاوت **باگ سمت کلاینت** است، پس `409` برمی‌گردد نه اینکه بی‌صدا نادیده گرفته شود. کسری که رد شده باشد کلید را مصرف نمی‌کند و همان `request_id` بعداً قابل استفاده است.

**پول همه‌جا `Decimal(18, 2)` است**، هرگز float. ورودی به‌صورت رشته پارس می‌شود و حداکثر دو رقم اعشار می‌گیرد.

**دفتر تراکنش‌ها append-only است و سه لایه از آن محافظت می‌کند:** متدهای نوشتن اصلاً route نشده‌اند (پس `405` برمی‌گردانند)، `Transaction.save()/delete()` روی ردیف موجود خطا می‌دهند، و یک تریگر `BEFORE UPDATE OR DELETE` در پستگرس هر مسیر دیگری را می‌بندد — SQL خام، `.update()`، یا یک سشن psql. هر ردیف `balance_after` را نگه می‌دارد.

**دفتر به یک ترتیب کلی نیاز دارد و timestamp آن را نمی‌دهد.** رزولوشن ساعت باعث تساوی می‌شود (روی ویندوز چند ردیف در یک تیک ~۱۵ میلی‌ثانیه‌ای می‌افتند) و UUID تصادفی tie-breaker نیست. پس هر ردیف یک `sequence` از یک sequence پستگرس می‌گیرد و ترتیب بر اساس آن است؛ چون درج‌ها زیر قفل ردیف کیف پول انجام می‌شوند، ترتیب درج همان ترتیب commit است.

**قیدها در schema هستند.** `balance >= 0`، `amount > 0` و `balance_after >= 0` هر سه `CHECK` هستند تا حتی باگ کد آینده هم نتواند وضعیت ناممکن ذخیره کند. کلید خارجی کیف پول `PROTECT` است تا تاریخچه بی‌صاحب نماند.

**`ATOMIC_REQUESTS` استفاده نشده** چون قفل ردیف را تا پایان کل درخواست نگه می‌داشت؛ قفل به‌صورت صریح و تا حد ممکن دیرتر و کوتاه‌تر گرفته می‌شود.

احراز هویت، درگاه پرداخت، پنل مدیریت، رابط کاربری و استقرار خارج از محدوده این تست هستند؛ به همین دلیل `django.contrib.auth` و `sessions` و `admin` اصلاً نصب نشده‌اند.

## پوشش خواسته‌ها

| # | خواسته | محل اثبات |
| --- | --- | --- |
| و ۱  ۲  | API موجودی، تراکنش‌ها و کسر | `tests/test_api.py` |
| ۳ | موجودی هرگز منفی نمی‌شود | `tests/test_negative_balance.py` |
| ۴ | ارسال مجدد `request_id` کسر دوباره نمی‌کند | `tests/test_idempotency.py` |
| ۵ | همان `request_id` با مبلغ متفاوت خطا می‌دهد | `tests/test_idempotency.py` |
| ۶ | دو کسر هم‌زمان ۸۰ واحدی، دقیقاً یکی موفق | `tests/test_concurrency.py` |
| ۷ | تراکنش ثبت‌شده قابل ویرایش یا حذف نیست | `tests/test_immutability.py` |

متغیرهای محیطی در `.env.example` آمده‌اند و هیچ مقدار محرمانه‌ای در مخزن نیست.
