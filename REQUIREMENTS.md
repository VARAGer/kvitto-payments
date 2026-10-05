# Финальная матрица требований

Источник: все 3 страницы PDF «Тестовое — Junior Python (FastAPI) — Квитто». Аудит 05–06.10.2026. По проекту: **30 PASS, 0 FAIL**; внешнее действие сдачи: **1 FAIL (нет подтверждения отправки)**. Одна строка — одна проверяемая группа требований.

| № | Требование | Где реализовано | Как фактически проверено | Итог |
| --- | --- | --- | --- | --- |
| 1 | Python 3.11+ | pyproject.toml | Чистый venv: Python 3.11.16 | PASS |
| 2 | FastAPI, Pydantic v2 | pyproject.toml, app/schemas.py | Версии 0.142.2/2.13.5, HTTP, OpenAPI | PASS |
| 3 | SQLite/PostgreSQL через ORM | app/db.py, app/models.py | SQLite + SQLAlchemy 2.1.3, таблицы и обе стороны связи ORM | PASS |
| 4 | pytest + httpx | pyproject.toml, tests/test_api.py | Чистая установка и pytest | PASS |
| 5 | Три тарифа с ценами при старте | app/db.py | HTTP: basic 990000, standard 1990000, premium 2990000; рестарт без дублей | PASS |
| 6 | Целые копейки, без float | app/models.py, app/main.py | Типы JSON; SQL typeof(amount/discount)=integer | PASS |
| 7 | Скидка KVITTO10 ровно 10% | app/main.py | Все тарифы с промо и без; amount+discount=price | PASS |
| 8 | Регистр промо не важен | app/schemas.py | KVITTO10, kvitto10, KvItTo10 через HTTP | PASS |
| 9 | Неизвестный промо → 422 | app/schemas.py | WRONG → стандартный detail/422 | PASS |
| 10 | card, sbp, installment | app/schemas.py | Все методы через HTTP; cash → 422 | PASS |
| 11 | Рассрочка требует 3/6/12 | app/schemas.py | Все сроки; отсутствующий срок и 5 → 422 | PASS |
| 12 | Сумма графика = amount | app/main.py | Все тарифы и сроки с промо/без, HTTP и pytest | PASS |
| 13 | Остаток в первых платежах | app/main.py | Точный divmod; standard/3=[663334,663333,663333] | PASS |
| 14 | График — int-список или null, без дат | app/schemas.py | Проверка JSON для всех методов | PASS |
| 15 | Новый платёж pending | app/models.py | Все ответы создания | PASS |
| 16 | Только три разрешённых перехода | app/main.py | Все 16 пар статусов через HTTP и pytest | PASS |
| 17 | Запрещённый переход → 409/error, без изменения | app/main.py | Все запрещённые пары; после фикса 25 гонок → один 200/один 409 | PASS |
| 18 | GET /tariffs → 200, id/title/price | app/main.py, app/schemas.py | Точное тело, curl README | PASS |
| 19 | POST /payments: тело, создание → 201 | app/main.py, app/schemas.py | Комбинации методов/промо/сроков, curl | PASS |
| 20 | Повтор ключа → тот же платёж 200, без дубля | app/main.py, app/models.py | Повтор и другое валидное тело; 10 конкурентных запросов → один 201; ключ после рестарта | PASS |
| 21 | GET существующего платежа → 200 | app/main.py | Тело совпадает с ответом создания | PASS |
| 22 | GET отсутствующего платежа → 404 | app/main.py | /payments/999999, pytest | PASS |
| 23 | Вебхук отсутствующего платежа → 404 | app/main.py | HTTP и pytest | PASS |
| 24 | Вебхук успех → 200 {result:ok} | app/main.py | Все разрешённые переходы, curl | PASS |
| 25 | Все 11 полей платежа | app/schemas.py | Точное множество полей, типы, datetime; внутренний ключ не выдаётся | PASS |
| 26 | Стандартные ошибки валидации 422 | app/schemas.py, app/main.py | Email, метод, срок, ID, статус, заголовок, пустое/необъектное тело, повреждённый JSON, неверный путь | PASS |
| 27 | ≥5 тестов с обязательными сценариями | tests/ | Текущий полный прогон с бонусами: 47 passed / 0 failed | PASS |
| 28 | README: запуск, тесты, curl | README.md | Чистый clone/venv/pip, .env и миграции; uvicorn --reload; 7 curl; pip check | PASS |
| 29 | AI_LOG: инструменты/модель, 2–3 запроса, ошибка | AI_LOG.md | Ручная сверка: 3 запроса, реальная гонка и её воспроизведение/исправление | PASS |
| 30 | GitHub-репозиторий с доступом | VARAGer/kvitto-payments | Публичный clone; опубликованное дерево сравнивается с локальным | PASS |
| 31 | Ссылка в исходный чат работодателя | Внешнее действие | Подтверждения отправки нет, выполняет кандидат | FAIL |

Дата получения задания неизвестна: срок «3 дня» нельзя подтвердить по времени PDF или коммитам. «≈3 часа» — оценка чистого времени. Способность кандидата объяснить код проверяется на собеседовании; для подготовки есть STUDY_GUIDE.md.

Бонусы реализованы по дополнительному запросу. Все шесть бонусов подтверждены. [Успешный CI](https://github.com/VARAGer/kvitto-payments/actions/runs/37372907698):

| Бонус | Где реализовано | Проверка | Итог |
| --- | --- | --- | --- |
| Docker Compose | Dockerfile, compose.yaml, .dockerignore | CI: build, live API и restart/persistence прошли; локально Docker отсутствует | PASS |
| HMAC-SHA256 | app/security.py | Точные байты, отсутствие/ошибка подписи → 401, live smoke | PASS |
| Alembic | alembic.ini, migrations/ | upgrade/current/check, repeat/downgrade/upgrade, тесты | PASS |
| GET /payments с фильтрами | app/main.py | Email/status/AND, пустая выборка, 422, live smoke | PASS |
| GitHub Actions Ruff/pytest | .github/workflows/ci.yml | Локальные проверки и единый CI job прошли | PASS |
| Правила Codex | AGENTS.md | Содержательные правила в корне репозитория | PASS |

Неоднозначности: amount — итог после скидки, discount — её величина. ID тарифов 1/2/3; title — basic/standard/premium. Повтор ключа возвращает первый платёж при другом валидном теле; Pydantic проверяет тело до endpoint. Для card/sbp срок не допускается. Неизвестный статус → 422, известный запрещённый переход → 409. Отсутствующий тариф при создании → 404.

Дополнительные требования пользователя после аудита (не относятся к бонусам PDF):

| Требование | Где реализовано | Фактическая проверка | Итог |
| --- | --- | --- | --- |
| Вызываемый рефанд | POST /payments/{id}/refund | Uvicorn: succeeded → refunded/200; остальные статусы → 409; 404/422; pytest и две конкурентные комбинации | PASS |
| Health | GET /health, HealthOut | Uvicorn: SELECT 1 и 200; pytest: OperationalError даёт 503 | PASS |
