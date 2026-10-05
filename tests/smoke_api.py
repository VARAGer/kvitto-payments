import hashlib
import hmac
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")
SECRET = os.environ["WEBHOOK_SECRET"]
RECORD = Path(tempfile.gettempdir()) / "kvitto-smoke-payment.json"


def request(method, path, payload=None, signed=False, headers=None):
    body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
    headers = dict(headers or {})
    if body is not None:
        headers["Content-Type"] = "application/json"
    if signed:
        headers["X-Signature"] = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    req = Request(BASE_URL + path, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=5) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def main():
    assert request("GET", "/health") == (200, {"status": "ok"})
    if "--check-persistence" in sys.argv:
        saved = json.loads(RECORD.read_text())
        assert request("GET", f'/payments/{saved["id"]}') == (200, saved)
        assert len(request("GET", "/tariffs")[1]) == 3
        print("Restart: payment and tariffs persisted")
        return

    status, tariffs = request("GET", "/tariffs")
    assert status == 200 and [t["price"] for t in tariffs] == [990000, 1990000, 2990000]
    email = f"smoke-{uuid4().hex}@example.com"
    payload = {"tariff_id": 2, "email": email, "method": "installment", "installment_months": 3, "promo_code": "kvitto10"}
    key = {"Idempotency-Key": uuid4().hex}
    status, payment = request("POST", "/payments", payload, headers=key)
    assert status == 201 and payment["amount"] == 1791000 and payment["discount"] == 199000
    assert payment["schedule"] == [597000, 597000, 597000]
    assert request("POST", "/payments", payload, headers=key) == (200, payment)
    webhook = {"payment_id": payment["id"], "status": "succeeded"}
    assert request("POST", "/webhooks/bank", webhook)[0] == 401
    assert request("GET", f'/payments/{payment["id"]}') == (200, payment)
    assert request("POST", "/webhooks/bank", webhook, signed=True) == (200, {"result": "ok"})
    status, payments = request("GET", "/payments?" + urlencode({"email": email, "status": "succeeded"}))
    assert status == 200 and [p["id"] for p in payments] == [payment["id"]]
    status, refunded = request("POST", f'/payments/{payment["id"]}/refund')
    assert status == 200 and refunded == {**payment, "status": "refunded"}
    assert request("POST", f'/payments/{payment["id"]}/refund')[0] == 409
    RECORD.write_text(json.dumps(refunded))
    print("Live API: health, tariffs, creation, idempotency, signature, filters, refund passed")


if __name__ == "__main__":
    main()
