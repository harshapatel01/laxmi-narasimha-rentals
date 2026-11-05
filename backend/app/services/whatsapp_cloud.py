import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

import httpx

from app.core.config import get_settings
from app.models.bookings import Booking

logger = logging.getLogger(__name__)
INDIA_TIMEZONE = ZoneInfo("Asia/Kolkata")
API_VERSION_PATTERN = re.compile(r"^v\d+\.\d+$")
TEMPLATE_NAME_PATTERN = re.compile(r"^[a-z0-9_]{1,512}$")
LANGUAGE_CODE_PATTERN = re.compile(r"^[a-z]{2}_[A-Z]{2}$")


@dataclass(frozen=True)
class WhatsAppSendResult:
    accepted: bool
    reason: Literal["accepted", "not_configured", "invalid_configuration", "provider_error"]


def _digits_only(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _send_template(
    *,
    template_name: str,
    language: str,
    components: list[dict[str, object]] | None = None,
) -> WhatsAppSendResult:
    settings = get_settings()
    access_token = settings.whatsapp_access_token
    phone_number_id = settings.whatsapp_phone_number_id
    admin_phone_number = settings.whatsapp_admin_phone_number
    api_version_value = settings.whatsapp_api_version
    required = {
        "WHATSAPP_ACCESS_TOKEN": access_token,
        "WHATSAPP_PHONE_NUMBER_ID": phone_number_id,
        "WHATSAPP_ADMIN_PHONE_NUMBER": admin_phone_number,
        "WHATSAPP_API_VERSION": api_version_value,
    }
    missing = [name for name, value in required.items() if not value or not value.strip()]
    if missing:
        logger.warning(
            "WhatsApp Cloud API is not configured; missing settings: %s.",
            ", ".join(missing),
        )
        return WhatsAppSendResult(False, "not_configured")

    assert access_token is not None
    assert phone_number_id is not None
    assert admin_phone_number is not None
    assert api_version_value is not None
    access_token = access_token.strip()
    phone_number_id = phone_number_id.strip()
    api_version = api_version_value.strip()
    recipient = _digits_only(admin_phone_number)
    if (
        not phone_number_id.isdigit()
        or not API_VERSION_PATTERN.fullmatch(api_version)
        or not 8 <= len(recipient) <= 15
        or not TEMPLATE_NAME_PATTERN.fullmatch(template_name)
        or not LANGUAGE_CODE_PATTERN.fullmatch(language)
    ):
        logger.error("WhatsApp Cloud API configuration has an invalid format.")
        return WhatsAppSendResult(False, "invalid_configuration")

    template: dict[str, object] = {
        "name": template_name,
        "language": {"code": language},
    }
    if components:
        template["components"] = components
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "template",
        "template": template,
    }
    endpoint = (
        f"https://graph.facebook.com/{api_version}/"
        f"{phone_number_id}/messages"
    )
    try:
        response = httpx.post(
            endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
            json=payload,
            timeout=10.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "WhatsApp Cloud API rejected a template message (HTTP %s).",
            exc.response.status_code,
        )
        return WhatsAppSendResult(False, "provider_error")
    except httpx.RequestError as exc:
        logger.warning(
            "WhatsApp Cloud API request failed (%s).",
            type(exc).__name__,
        )
        return WhatsAppSendResult(False, "provider_error")

    return WhatsAppSendResult(True, "accepted")


def send_whatsapp_connectivity_test() -> WhatsAppSendResult:
    """Send only Meta's generic hello_world template when explicitly invoked."""
    return _send_template(
        template_name="hello_world",
        language="en_US",
    )


def _format_booking_datetime(value: datetime) -> str:
    aware_value = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware_value.astimezone(INDIA_TIMEZONE).strftime(
        "%d %b %Y, %I:%M %p IST"
    )


def _booking_template_components(booking: Booking) -> list[dict[str, object]]:
    customer = booking.customer
    profile = customer.profile if customer else None
    customer_name = " ".join(
        part
        for part in (
            profile.first_name if profile else None,
            profile.last_name if profile else None,
        )
        if part and part.strip()
    ) or "Customer"
    customer_mobile = (
        customer.mobile.strip()
        if customer and customer.mobile and customer.mobile.strip()
        else "Mobile unavailable"
    )
    vehicle_name = f"{booking.vehicle.brand} {booking.vehicle.model}".strip()
    category_name = booking.vehicle.category.name if booking.vehicle.category else "Category unavailable"
    pickup_location = (
        booking.pickup_location.name
        if booking.pickup_location and booking.pickup_location.name
        else "Pickup location unavailable"
    )
    parameters = [
        booking.reference,
        f"{customer_name} | Mobile: {customer_mobile}",
        f"{vehicle_name} | Category: {category_name}",
        (
            f"Pickup location: {pickup_location} | "
            f"Pickup: {_format_booking_datetime(booking.start_at)} | "
            f"Return: {_format_booking_datetime(booking.end_at)} | "
            f"Status: {booking.status.replace('_', ' ').title()}"
        ),
    ]
    return [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": value}
                for value in parameters
            ],
        }
    ]


def send_booking_request_notification(booking: Booking) -> WhatsAppSendResult:
    settings = get_settings()
    template_name = settings.whatsapp_booking_template_name
    language = settings.whatsapp_booking_template_language
    if not template_name or not template_name.strip():
        logger.info(
            "WhatsApp booking notification skipped because "
            "WHATSAPP_BOOKING_TEMPLATE_NAME is not configured."
        )
        return WhatsAppSendResult(False, "not_configured")

    return _send_template(
        template_name=template_name.strip(),
        language=language.strip(),
        components=_booking_template_components(booking),
    )
