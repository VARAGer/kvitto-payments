import hashlib
import hmac
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.db import create_db_engine
from app.main import app
from tests.conftest import TEST_SECRET


def new_payment(client, email):
    response = client.post("/payments", json={"tariff_id": 1, "email": email, "method": "card"})
    assert response.status_code == 201
    return response.json()


def test_payment_list_filters(client):
    assert client.get("/payments").json() == []
    first = new_payment(client, "one@example.com")
    second = new_payment(client, "two@example.com")
    third = new_payment(client, "one@example.com")
    assert client.post(
        "/webhooks/bank", json={"payment_id": first["id"], "status": "succeeded"}
    ).status_code == 200

    def ids(**filters):
        response = client.get("/payments", params=filters)
        assert response.status_code == 200
        for payment in response.json():
            assert set(payment) == set(first)
        return [p["id"] for p in response.json()]

    assert ids() == [first["id"], second["id"], third["id"]]
    assert ids(email="one@example.com") == [first["id"], third["id"]]
    assert ids(status="pending") == [second["id"], third["id"]]
    assert ids(email="one@example.com", status="succeeded") == [first["id"]]
    assert ids(email="missing@example.com") == []
    assert ids(status="refunded") == []


@pytest.mark.parametrize("params", [{"email": "invalid"}, {"status": "unknown"}])
def test_invalid_payment_filters(client, params):
    response = client.get("/payments", params=params)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


@pytest.mark.parametrize("signature", [None, "wrong", "0" * 64])
def test_invalid_webhook_signature(client, signature):
    payment = new_payment(client, "student@example.com")
    client.event_hooks["request"].clear()
    headers = {"X-Signature": signature} if signature is not None else {}
    response = client.post(
        "/webhooks/bank",
        json={"payment_id": payment["id"], "status": "succeeded"},
        headers=headers,
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid signature"}
    assert client.get(f'/payments/{payment["id"]}').json()["status"] == "pending"


def test_signature_uses_exact_body_bytes(client):
    payment = new_payment(client, "student@example.com")
    body = f'{{ "payment_id": {payment["id"]}, "status": "succeeded" }}'.encode()
    signature = hmac.new(TEST_SECRET.encode(), body, hashlib.sha256).hexdigest()
    headers = {"Content-Type": "application/json", "X-Signature": signature}
    tampered = client.post("/webhooks/bank", content=body + b" ", headers=headers)
    assert tampered.status_code == 401
    valid = client.post("/webhooks/bank", content=body, headers=headers)
    assert valid.status_code == 200
    assert client.get(f'/payments/{payment["id"]}').json()["status"] == "succeeded"


def test_missing_webhook_secret_prevents_startup(monkeypatch):
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="WEBHOOK_SECRET"):
        with TestClient(app):
            pass


def test_migration_upgrade_repeat_and_downgrade(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    engine = create_db_engine(database_url)
    assert {"tariffs", "payments", "alembic_version"} <= set(inspect(engine).get_table_names())
    engine.dispose()
    command.check(config)
    command.downgrade(config, "base")
    engine = create_db_engine(database_url)
    assert "tariffs" not in inspect(engine).get_table_names()
    assert "payments" not in inspect(engine).get_table_names()
    engine.dispose()
    command.upgrade(config, "head")
