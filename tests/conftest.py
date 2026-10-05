import hashlib
import hmac
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.main import app

TEST_SECRET = "test-only-webhook-secret"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("WEBHOOK_SECRET", TEST_SECRET)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")

    def sign_webhook(request):
        if request.url.path == "/webhooks/bank" and "X-Signature" not in request.headers:
            request.headers["X-Signature"] = hmac.new(
                TEST_SECRET.encode(), request.content, hashlib.sha256
            ).hexdigest()

    with TestClient(app) as test_client:
        test_client.event_hooks["request"].append(sign_webhook)
        yield test_client
