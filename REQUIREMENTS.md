# Сверка с тестовым заданием

| Требование | Реализация | Проверка |
| --- | --- | --- |
| Python 3.11+, FastAPI, Pydantic v2, ORM, SQLite | `pyproject.toml`, `app/` | запуск и `pytest` |
| Три тарифа при старте, цены в копейках | `app/db.py`, `app/models.py` | `test_tariffs` |
| KVITTO10, скидка 10%, неизвестный код 422 | `app/schemas.py`, `app/main.py` | `test_amounts_and_promo` |
| Методы оплаты, срок рассрочки 3/6/12 | `app/schemas.py` | `test_payment_validation` |
| Точный график, остаток в первых платежах | `app/main.py` | `test_installment_schedules` |
| Статусы и допустимые переходы | `app/main.py` | `test_webhook_transitions` |
| GET /tariffs → 200 | `app/main.py` | `test_tariffs` |
| POST /payments → 201, повтор ключа → 200 | `app/main.py` | `test_idempotency` |
| GET /payments/{id} → 200/404 | `app/main.py` | `test_missing_payment` |
| POST /webhooks/bank → 200/404/409 | `app/main.py` | `test_webhook_transitions` |
| Полный ответ платежа, стандартные 422 | `app/schemas.py`, `app/main.py` | тесты API |
| README, AI_LOG, минимум 5 тестов | файлы в корне, `tests/` | `pytest` и ручная сверка |

Бонусы не входят в обязательный объём: Docker, подпись вебхука, Alembic, список платежей, CI, правила ассистента. Сдача требует GitHub-репозиторий и отправку ссылки в исходный чат; публикация выполняется отдельно после проверки локального проекта.

Уточнения к неоднозначным местам: `amount` — сумма к оплате после скидки, `discount` — величина скидки. ID тарифов фиксированы (1, 2, 3), `title` равен имени тарифа. Повторный `Idempotency-Key` возвращает исходный платёж даже при отличающемся новом теле запроса; корректность самого тела FastAPI проверяет до входа в endpoint. Для `card`/`sbp` срок рассрочки недопустим. Неверный статус вебхука даёт 422, известный, но запрещённый переход — 409.
