import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    with TestClient(app) as test_client:
        yield test_client


def payload(**changes):
    data = {"tariff_id": 2, "email": "student@example.com", "method": "card"}
    data.update(changes)
    return data


def test_tariffs(client):
    response = client.get("/tariffs")
    assert response.status_code == 200
    assert response.json() == [
        {"id": 1, "title": "basic", "price": 990000},
        {"id": 2, "title": "standard", "price": 1990000},
        {"id": 3, "title": "premium", "price": 2990000},
    ]


def test_amounts_and_promo(client):
    plain = client.post("/payments", json=payload())
    promo = client.post("/payments", json=payload(promo_code="kvitto10"))
    assert plain.status_code == promo.status_code == 201
    assert plain.json()["amount"] == 1990000
    assert plain.json()["discount"] == 0
    assert promo.json()["amount"] == 1791000
    assert promo.json()["discount"] == 199000
    assert promo.json()["status"] == "pending"
    assert promo.json()["schedule"] is None
    assert promo.json()["installment_months"] is None
    assert set(promo.json()) == {
        "id", "status", "tariff_id", "amount", "discount", "method",
        "installment_months", "schedule", "email", "created_at",
    }
    assert client.post("/payments", json=payload(promo_code="WRONG")).status_code == 422


@pytest.mark.parametrize("months", [3, 6, 12])
def test_installment_schedules(client, months):
    response = client.post(
        "/payments", json=payload(method="installment", installment_months=months)
    )
    assert response.status_code == 201
    payment = response.json()
    schedule = payment["schedule"]
    assert len(schedule) == months
    assert sum(schedule) == payment["amount"] == 1990000
    assert max(schedule) - min(schedule) <= 1
    assert schedule == sorted(schedule, reverse=True)
    if months == 3:
        assert schedule == [663334, 663333, 663333]


def test_idempotency(client):
    headers = {"Idempotency-Key": "order-123"}
    first = client.post("/payments", json=payload(), headers=headers)
    again = client.post("/payments", json=payload(), headers=headers)
    assert first.status_code == 201
    assert again.status_code == 200
    assert first.json() == again.json()
    without_key = client.post("/payments", json=payload())
    assert without_key.status_code == 201
    assert without_key.json()["id"] == first.json()["id"] + 1


def test_idempotency_returns_original_payment_for_changed_valid_body(client):
    headers = {"Idempotency-Key": "another-order"}
    first = client.post("/payments", json=payload(), headers=headers)
    again = client.post("/payments", json=payload(tariff_id=3), headers=headers)
    assert first.status_code == 201
    assert again.status_code == 200
    assert again.json() == first.json()


def test_payment_validation(client):
    invalid = [
        payload(method="installment"),
        payload(method="installment", installment_months=5),
        payload(method="card", installment_months=3),
        payload(method="cash"),
        payload(email="not-an-email"),
    ]
    for data in invalid:
        response = client.post("/payments", json=data)
        assert response.status_code == 422
        assert "detail" in response.json()
    assert client.post("/payments", json=payload(tariff_id=999)).status_code == 404


def test_missing_payment(client):
    assert client.get("/payments/999").status_code == 404
    assert client.post(
        "/webhooks/bank", json={"payment_id": 999, "status": "succeeded"}
    ).status_code == 404


def test_webhook_transitions(client):
    payment_id = client.post("/payments", json=payload()).json()["id"]

    def notify(status):
        return client.post("/webhooks/bank", json={"payment_id": payment_id, "status": status})

    rejected = notify("refunded")
    assert rejected.status_code == 409
    assert rejected.json() == {"error": "invalid_transition"}
    assert client.get(f"/payments/{payment_id}").json()["status"] == "pending"
    assert notify("succeeded").json() == {"result": "ok"}
    assert client.get(f"/payments/{payment_id}").json()["status"] == "succeeded"
    rejected = notify("failed")
    assert rejected.status_code == 409
    assert client.get(f"/payments/{payment_id}").json()["status"] == "succeeded"
    assert notify("refunded").status_code == 200
    assert client.get(f"/payments/{payment_id}").json()["status"] == "refunded"
    assert notify("refunded").status_code == 409
    assert notify("unknown").status_code == 422


def test_failed_payment_cannot_change_status(client):
    payment_id = client.post("/payments", json=payload()).json()["id"]
    failed = client.post(
        "/webhooks/bank", json={"payment_id": payment_id, "status": "failed"}
    )
    assert failed.status_code == 200
    rejected = client.post(
        "/webhooks/bank", json={"payment_id": payment_id, "status": "succeeded"}
    )
    assert rejected.status_code == 409
    assert rejected.json() == {"error": "invalid_transition"}
    assert client.get(f"/payments/{payment_id}").json()["status"] == "failed"
