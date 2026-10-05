# Квитто Payments API

API оплаты курсов: тарифы, платежи, рассрочка, промокод, возврат и уведомления банка. Все денежные суммы — целые копейки. Реализованы обязательная часть ТЗ, все шесть бонусов, а также рефанд и health по дополнительному запросу.

Стек: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2, SQLite, Alembic, pytest/httpx, Ruff, Docker Compose и GitHub Actions.

## Локальный запуск

Из корня проекта:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test,dev]'
```

При первом запуске создайте локальный `.env` с новым случайным секретом:

```bash
cp .env.example .env
python - <<'PY'
from pathlib import Path
from secrets import token_hex
p = Path('.env')
p.write_text(p.read_text().replace('WEBHOOK_SECRET=\n', f'WEBHOOK_SECRET={token_hex(32)}\n'))
PY
```

Загрузите окружение, примените миграции и запустите API:

```bash
set -a
source .env
set +a
alembic upgrade head
uvicorn app.main:app --reload
```

Используйте установленный Python 3.11 или новее, если команда `python3.11` называется иначе. API: `http://127.0.0.1:8000`; Swagger: `/docs`. Таблицы создаются Alembic, при старте приложения добавляются три тарифа. SQLite-файл сохраняет платежи после перезапуска.

## Запуск через Docker

Нужен Docker с Compose v2. Создайте `.env` как выше или скопируйте `.env.example` и самостоятельно заполните `WEBHOOK_SECRET` случайным секретом. Затем:

```bash
docker compose up
```

Compose собирает образ, применяет миграции и запускает API на порту 8000. SQLite хранится в volume `payments_data`. Обычная остановка сохраняет данные:

```bash
docker compose down
```

Healthcheck контейнера обращается к `/health`. Docker-версия использует `sqlite:////data/payments.db`, независимо от локального DATABASE_URL.

## Конфигурация и миграции

| Переменная | Назначение |
| --- | --- |
| DATABASE_URL | Необязательна для локального запуска, по умолчанию `sqlite:///./payments.db`. Используется и API, и Alembic. |
| WEBHOOK_SECRET | Обязательный непустой секрет для HMAC вебхука. Без него API не запускается. Один и тот же секрет нужен отправителю уведомления и серверу. |

Локальный Uvicorn сам `.env` не читает: загрузите его командами `set -a` / `source .env` / `set +a`. Compose автоматически читает `.env`. Файл исключён из Git и Docker build context. Не пересоздавайте секрет при каждом запуске, если отправитель банка уже настроен на него.

```bash
alembic upgrade head
alembic current
alembic check
```

Миграция `0001` создаёт tariffs и payments. Новые изменения схемы добавляйте отдельными миграциями. Если осталась база от ранней версии проекта, которая создавалась через `create_all`, предварительно сделайте её резервную копию. Только для неизменённой схемы ранней версии этого проекта можно выполнить `alembic stamp 0001`, затем `alembic upgrade head`: stamp отмечает уже существующую схему, не создавая таблицы повторно. Для новой БД используйте обычный upgrade. Downgrade до base удаляет таблицы и предназначен для временной тестовой базы.

## Проверки

```bash
ruff check .
pytest -q
```

Тесты создают отдельную временную SQLite-базу через настоящую миграцию. Проверяются суммы, промо, график, повтор ключа, все переходы, возврат, health, гонки, внешний ключ, фильтры, HMAC и upgrade/downgrade. В тестах используется открытый фиктивный секрет, который не является секретом запуска приложения.

GitHub Actions выполняет Ruff и pytest на каждый push и pull request. Затем в том же job собирается и запускается Docker Compose, проверяются реальный API и сохранение данных после рестарта. Для CI секрет генерируется на один запуск. Проверку живого API можно повторить локально при запущенном сервере и загруженном WEBHOOK_SECRET:

```bash
python tests/smoke_api.py
```

Правила Codex для проекта находятся в `AGENTS.md`: деньги, статусы, подпись, миграции и проверки перед сдачей. Формат соответствует [официальной документации AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

## API

| Метод и путь | Результат |
| --- | --- |
| GET /tariffs | 200, список тарифов с id/title/price |
| POST /payments | 201, новый платёж; 200, повтор Idempotency-Key |
| GET /payments | 200, список; фильтры email и status, вместе работают как AND |
| GET /payments/{id} | 200, платёж; 404, если не найден |
| POST /payments/{id}/refund | 200, платёж с refunded; 404; 409 при статусе, отличном от succeeded |
| POST /webhooks/bank | 200 при разрешённом переходе; 401 при отсутствующей/неверной подписи; 404; 409 |
| GET /health | 200 {"status":"ok"}; 503 при ошибке запроса к БД |

Валидация — стандартный 422 FastAPI. Методы оплаты: card, sbp, installment. Для рассрочки обязателен срок 3/6/12 месяцев. KVITTO10 уменьшает цену на 10% независимо от регистра. amount — итог к оплате, discount — скидка. Новый статус pending, разрешены pending → succeeded/failed и succeeded → refunded. Пустая выборка платежей возвращает [], неверные фильтры — 422.

Рефанд вызывается без тела, меняет статус и сохраняет суммы. Повторный возврат — 409. Это модель оплаты для тестового: настоящая банковская операция не выполняется. Рефанд и вебхук используют общую атомарную проверку переходов.

## Примеры запросов

В терминале для curl загрузите тот же `.env`, что используется сервером. На новой БД первый платёж будет иметь ID 1; для последующих подставляйте ID из ответа создания.

```bash
curl http://127.0.0.1:8000/tariffs

curl -X POST http://127.0.0.1:8000/payments \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: order-123' \
  -d '{"tariff_id":2,"email":"student@example.com","method":"installment","installment_months":3,"promo_code":"kvitto10"}'

curl http://127.0.0.1:8000/payments/1

body='{"payment_id":1,"status":"succeeded"}'
signature=$(printf '%s' "$body" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" | awk '{print $NF}')
curl -X POST http://127.0.0.1:8000/webhooks/bank \
  -H 'Content-Type: application/json' \
  -H "X-Signature: $signature" \
  --data-binary "$body"

curl 'http://127.0.0.1:8000/payments?email=student%40example.com&status=succeeded'
curl -X POST http://127.0.0.1:8000/payments/1/refund
curl http://127.0.0.1:8000/health
```

X-Signature — lowercase hex HMAC-SHA256 от **точных байтов** тела, без префикса. Любое изменение пробелов или переводов строк требует новой подписи. Idempotency-Key возвращает первый платёж даже при другом валидном теле; при отсутствии ключа создаётся новый платёж.

Результаты проверок: `AUDIT_REPORT.md`, матрица: `REQUIREMENTS.md`, подготовка к собеседованию: `STUDY_GUIDE.md`.
