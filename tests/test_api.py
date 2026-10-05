from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.main import app
from app.models import Payment


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


def test_concurrent_webhooks_allow_only_one_transition(client):
    payment_id = client.post("/payments", json=payload()).json()["id"]
    barrier = Barrier(2)

    def wait_for_both_reads(payment, context):
        barrier.wait(timeout=5)

    event.listen(Payment, "load", wait_for_both_reads)
    try:
        def notify(status):
            return client.post(
                "/webhooks/bank", json={"payment_id": payment_id, "status": status}
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(notify, ["succeeded", "failed"]))
    finally:
        event.remove(Payment, "load", wait_for_both_reads)

    assert sorted(reply.status_code for reply in replies) == [200, 409]
    winner = ["succeeded", "failed"][next(i for i, r in enumerate(replies) if r.status_code == 200)]
    assert client.get(f"/payments/{payment_id}").json()["status"] == winner
    assert next(r for r in replies if r.status_code == 409).json() == {"error": "invalid_transition"}


def test_database_rejects_missing_tariff(client):
    with app.state.session_factory() as session:
        session.add(Payment(
            tariff_id=999,
            amount=990000,
            discount=0,
            method="card",
            email="student@example.com",
        ))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


@pytest.mark.parametrize("current", ["pending", "succeeded", "failed", "refunded"])
@pytest.mark.parametrize("target", ["pending", "succeeded", "failed", "refunded"])
def test_all_status_transitions(client, current, target):
    payment_id = client.post("/payments", json=payload()).json()["id"]

    def notify(status):
        return client.post("/webhooks/bank", json={"payment_id": payment_id, "status": status})

    if current in {"succeeded", "refunded"}:
        assert notify("succeeded").status_code == 200
    if current in {"failed", "refunded"}:
        assert notify(current).status_code == 200

    valid = (current, target) in {
        ("pending", "succeeded"), ("pending", "failed"), ("succeeded", "refunded")
    }
    response = notify(target)
    assert response.status_code == (200 if valid else 409)
    assert response.json() == ({"result": "ok"} if valid else {"error": "invalid_transition"})
    assert client.get(f"/payments/{payment_id}").json()["status"] == (target if valid else current)


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_reports_database_failure(client, monkeypatch):
    def unavailable(self, *args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection failed"))

    monkeypatch.setattr(Session, "execute", unavailable)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}


def test_refund_succeeded_payment(client):
    payment = client.post("/payments", json=payload()).json()
    assert client.post(
        "/webhooks/bank", json={"payment_id": payment["id"], "status": "succeeded"}
    ).status_code == 200
    response = client.post(f'/payments/{payment["id"]}/refund')
    assert response.status_code == 200
    assert response.json() == {**payment, "status": "refunded"}
    assert client.get(f'/payments/{payment["id"]}').json() == response.json()


@pytest.mark.parametrize("current", ["pending", "failed", "refunded"])
def test_refund_rejects_invalid_state(client, current):
    payment_id = client.post("/payments", json=payload()).json()["id"]
    if current == "refunded":
        assert client.post(
            "/webhooks/bank", json={"payment_id": payment_id, "status": "succeeded"}
        ).status_code == 200
    if current != "pending":
        assert client.post(
            "/webhooks/bank", json={"payment_id": payment_id, "status": current}
        ).status_code == 200
    response = client.post(f"/payments/{payment_id}/refund")
    assert response.status_code == 409
    assert response.json() == {"error": "invalid_transition"}
    assert client.get(f"/payments/{payment_id}").json()["status"] == current


def test_refund_missing_or_invalid_id(client):
    assert client.post("/payments/999/refund").status_code == 404
    response = client.post("/payments/not-an-id/refund")
    assert response.status_code == 422
    assert "detail" in response.json()


@pytest.mark.parametrize("other_request", ["refund", "webhook"])
def test_concurrent_refunds_allow_only_one_transition(client, other_request):
    payment_id = client.post("/payments", json=payload()).json()["id"]
    assert client.post(
        "/webhooks/bank", json={"payment_id": payment_id, "status": "succeeded"}
    ).status_code == 200
    barrier = Barrier(2)

    def wait_for_both_reads(payment, context):
        barrier.wait(timeout=5)

    def request_refund(kind):
        if kind == "refund":
            return client.post(f"/payments/{payment_id}/refund")
        return client.post("/webhooks/bank", json={"payment_id": payment_id, "status": "refunded"})

    event.listen(Payment, "load", wait_for_both_reads)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(request_refund, ["refund", other_request]))
    finally:
        event.remove(Payment, "load", wait_for_both_reads)
    assert sorted(r.status_code for r in replies) == [200, 409]
    assert next(r for r in replies if r.status_code == 409).json() == {"error": "invalid_transition"}
    assert client.get(f"/payments/{payment_id}").json()["status"] == "refunded"
