import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.api.v1.whatsapp_webhook import extract_delivery_statuses
from app.core.config import get_settings
from app.main import app

WEBHOOK_URL = "/api/v1/webhooks/whatsapp"
TEST_VERIFY_TOKEN = "test-only-whatsapp-verify-token"
TEST_APP_SECRET = "test-only-meta-app-secret"


@pytest.fixture
def whatsapp_client(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "whatsapp_webhook_verify_token", TEST_VERIFY_TOKEN)
    monkeypatch.setattr(settings, "whatsapp_app_secret", TEST_APP_SECRET)
    with TestClient(app) as client:
        yield client


def signed_headers(body: bytes, app_secret: str = TEST_APP_SECRET) -> dict[str, str]:
    signature = hmac.new(
        app_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return {"X-Hub-Signature-256": f"sha256={signature}"}


def test_webhook_verification_returns_challenge_for_valid_token(whatsapp_client):
    response = whatsapp_client.get(
        WEBHOOK_URL,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": TEST_VERIFY_TOKEN,
            "hub.challenge": "challenge-value",
        },
    )

    assert response.status_code == 200
    assert response.text == "challenge-value"
    assert response.headers["content-type"].startswith("text/plain")


@pytest.mark.parametrize(
    "params",
    [
        {
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "challenge-value",
        },
        {
            "hub.mode": "unsubscribe",
            "hub.verify_token": TEST_VERIFY_TOKEN,
            "hub.challenge": "challenge-value",
        },
    ],
)
def test_webhook_verification_rejects_invalid_mode_or_token(whatsapp_client, params):
    response = whatsapp_client.get(WEBHOOK_URL, params=params)

    assert response.status_code == 403
    assert response.json()["detail"] == "WhatsApp webhook verification failed."


def test_webhook_verification_rejects_missing_challenge(whatsapp_client):
    response = whatsapp_client.get(
        WEBHOOK_URL,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": TEST_VERIFY_TOKEN,
        },
    )

    assert response.status_code == 400


def test_post_accepts_valid_signature_and_parses_delivery_statuses(whatsapp_client):
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "statuses": [
                                {"id": "message-1", "status": "sent", "timestamp": "1"},
                                {"id": "message-2", "status": "delivered", "timestamp": "2"},
                                {"id": "message-3", "status": "read", "timestamp": "3"},
                                {"id": "message-4", "status": "failed", "timestamp": "4"},
                            ]
                        },
                    }
                ]
            }
        ],
    }
    body = json.dumps(payload).encode("utf-8")

    response = whatsapp_client.post(
        WEBHOOK_URL,
        content=body,
        headers=signed_headers(body),
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "delivery_status_updates": 4}


def test_post_rejects_missing_or_invalid_signature(whatsapp_client):
    body = b'{"object":"whatsapp_business_account"}'

    missing = whatsapp_client.post(WEBHOOK_URL, content=body)
    invalid = whatsapp_client.post(
        WEBHOOK_URL,
        content=body,
        headers={"X-Hub-Signature-256": "sha256=" + ("0" * 64)},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert missing.json() == invalid.json()


def test_post_rejects_signed_non_json_body(whatsapp_client):
    body = b"not-json"

    response = whatsapp_client.post(
        WEBHOOK_URL,
        content=body,
        headers=signed_headers(body),
    )

    assert response.status_code == 400


def test_status_parser_ignores_malformed_and_unknown_events():
    payload = {
        "entry": [
            None,
            {
                "changes": [
                    None,
                    {
                        "value": {
                            "statuses": [
                                {"status": "delivered"},
                                {"status": "unknown"},
                                {"status": 12},
                                None,
                            ]
                        }
                    },
                    {"value": {"statuses": "not-a-list"}},
                ]
            },
        ]
    }

    assert extract_delivery_statuses(payload) == ["delivered"]
