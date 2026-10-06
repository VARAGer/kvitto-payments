import json

import pytest
from sqlalchemy.orm import sessionmaker

from app.db import create_db_engine
from app.main import app


def request_with_id(client, operation, value):
    if operation == "create":
        return client.post("/payments", json={
            "tariff_id": value, "email": "student@example.com", "method": "card"
        })
    if operation == "get":
        return client.get(f"/payments/{value}")
    if operation == "refund":
        return client.post(f"/payments/{value}/refund")
    return client.post("/webhooks/bank", json={"payment_id": value, "status": "succeeded"})


@pytest.mark.parametrize("operation", ["create", "get", "refund", "webhook"])
@pytest.mark.parametrize("value", [2**63, 10**100, -(10**100)])
def test_id_outside_database_range(client, operation, value):
    response = request_with_id(client, operation, value)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert client.get("/payments").json() == []


def test_largest_valid_id_is_not_found(client):
    for operation in ["create", "get", "refund", "webhook"]:
        assert request_with_id(client, operation, 2**63 - 1).status_code == 404


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1e309"])
def test_nonfinite_number_returns_validation_error(client, value):
    body = '{"tariff_id":' + value + ',"email":"student@example.com","method":"card"}'
    response = client.post("/payments", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert client.get("/payments").json() == []


def test_invalid_utf8_in_non_json_body_returns_validation_error(client):
    response = client.post("/payments", content=b"\xff", headers={"Content-Type": "text/plain"})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_unpaired_unicode_surrogate_returns_validation_error(client):
    body = json.dumps({"tariff_id": 1, "email": "\ud800", "method": "card"}).encode()
    response = client.post("/payments", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


@pytest.mark.parametrize("kind", ["empty", "corrupt", "unavailable"])
def test_health_with_unusable_database(client, tmp_path, monkeypatch, kind):
    path = tmp_path / "broken.db"
    if kind == "corrupt":
        path.write_bytes(b"not a SQLite database")
    elif kind == "unavailable":
        path = tmp_path / "missing-directory" / "broken.db"
    engine = create_db_engine(f"sqlite:///{path}")
    monkeypatch.setattr(app.state, "session_factory", sessionmaker(engine))
    try:
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json() == {"detail": "database unavailable"}
        assert str(path) not in response.text
    finally:
        engine.dispose()
