import hashlib
import hmac
import json
import logging
from collections import Counter
from typing import TypeAlias

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks/whatsapp", tags=["WhatsApp webhook"])

WhatsAppPayload: TypeAlias = dict[str, object]
DELIVERY_STATUSES = frozenset({"sent", "delivered", "read", "failed"})


def extract_delivery_statuses(payload: WhatsAppPayload) -> list[str]:
    statuses: list[str] = []
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return statuses

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict):
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            events = value.get("statuses")
            if not isinstance(events, list):
                continue
            for event in events:
                if not isinstance(event, dict):
                    continue
                delivery_status = event.get("status")
                if isinstance(delivery_status, str) and delivery_status in DELIVERY_STATUSES:
                    statuses.append(delivery_status)
    return statuses


@router.get("")
def verify_whatsapp_webhook(request: Request) -> Response:
    settings = get_settings()
    verify_token = settings.whatsapp_webhook_verify_token
    if not verify_token or not verify_token.strip():
        logger.error("WhatsApp webhook verification token is not configured.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp webhook verification is not configured.",
        )

    query = request.query_params
    supplied_token = query.get("hub.verify_token", "")
    if (
        query.get("hub.mode") != "subscribe"
        or not hmac.compare_digest(
            supplied_token.encode("utf-8"),
            verify_token.encode("utf-8"),
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="WhatsApp webhook verification failed.",
        )

    challenge = query.get("hub.challenge")
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook challenge is required.",
        )
    return Response(content=challenge, media_type="text/plain")


@router.post("")
async def receive_whatsapp_webhook(request: Request) -> dict[str, str | int]:
    app_secret = get_settings().whatsapp_app_secret
    if not app_secret or not app_secret.strip():
        logger.error("WhatsApp App Secret is not configured.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp webhook signature validation is not configured.",
        )

    body = await request.body()
    supplied_signature = request.headers.get("X-Hub-Signature-256", "")
    if not supplied_signature.startswith("sha256="):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature.",
        )
    expected_signature = "sha256=" + hmac.new(
        app_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature.",
        )

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook body must be valid JSON.",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook body must be a JSON object.",
        )

    delivery_statuses = extract_delivery_statuses(payload)
    if delivery_statuses:
        status_counts = dict(Counter(delivery_statuses))
        logger.info(
            "WhatsApp delivery status updates received.",
            extra={"delivery_status_counts": status_counts},
        )
    return {"status": "ok", "delivery_status_updates": len(delivery_statuses)}
