import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.dependencies import CUSTOMER_CSRF_COOKIE, CUSTOMER_SESSION_COOKIE
from app.db.session import get_db
from app.main import app
from app.models.auth import AuthSession, CustomerProfile, User
from app.models.base import Base
from app.models.bookings import Booking, BookingEvent, BookingNotification, BookingPayment
from app.models.vehicles import City, PickupLocation, Vehicle, VehicleCategory
from app.services.security import hash_token


@pytest.fixture
def customer_security_app():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    tokens: dict[str, tuple[str, str]] = {}
    with factory() as db:
        customers = {
            "a": User(mobile="+919876543210", email="customer-a@example.com", status="active"),
            "b": User(mobile="+919876543211", email="customer-b@example.com", status="active"),
            "blocked": User(mobile="+919876543212", email="blocked@example.com", status="blocked"),
        }
        db.add_all(customers.values())
        db.flush()
        db.add_all(
            [
                CustomerProfile(user_id=customers["a"].id, first_name="Customer", last_name="A"),
                CustomerProfile(user_id=customers["b"].id, first_name="Customer", last_name="B"),
                CustomerProfile(user_id=customers["blocked"].id, first_name="Blocked", last_name="Customer"),
            ]
        )

        city = City(name="Test City", state="Test State")
        category = VehicleCategory(name="Test Car")
        db.add_all([city, category])
        db.flush()
        location = PickupLocation(
            city_id=city.id,
            name="Test Pickup",
            address="123 Test Road",
        )
        db.add(location)
        db.flush()
        vehicle = Vehicle(
            vehicle_code="TEST-001",
            brand="Test",
            model="Vehicle",
            manufacturing_year=2025,
            registration_number="TS09AB1234",
            category_id=category.id,
            city_id=city.id,
            pickup_location_id=location.id,
            seating_capacity=5,
            fuel_type="petrol",
            transmission_type="manual",
            self_drive_enabled=True,
            daily_rental_enabled=True,
            daily_base_price=Decimal("1000.00"),
            advance_payment_amount=Decimal("100.00"),
            availability_status="available",
            is_active=True,
        )
        db.add(vehicle)
        db.flush()
        booking = Booking(
            reference="LNR-TEST-BOOKING",
            customer_id=customers["b"].id,
            vehicle_id=vehicle.id,
            city_id=city.id,
            pickup_location_id=location.id,
            start_at=datetime.now(UTC) + timedelta(days=4),
            end_at=datetime.now(UTC) + timedelta(days=5),
            rental_type="daily",
            driving_mode="self_drive",
            estimated_total=Decimal("1000.00"),
            daily_rate_snapshot=Decimal("1000.00"),
            advance_amount=Decimal("100.00"),
            amount_paid=Decimal("100.00"),
            remaining_balance=Decimal("900.00"),
            status="completed",
            payment_status="offline_paid",
            licence_verification_status="not_required",
            expires_at=datetime.now(UTC) + timedelta(days=2),
        )
        db.add(booking)
        db.flush()
        payment = BookingPayment(
            booking_id=booking.id,
            amount=Decimal("100.00"),
            payment_method="cash",
            status="verified",
            reference_note="Test payment",
        )
        db.add(payment)
        event = BookingEvent(
            booking_id=booking.id,
            actor_type="customer",
            actor_user_id=customers["b"].id,
            action="requested",
            to_status="pending",
        )
        mismatched_event = BookingEvent(
            booking_id=booking.id,
            actor_type="customer",
            actor_user_id=customers["b"].id,
            action="notification_created",
            to_status="completed",
        )
        db.add_all([event, mismatched_event])
        db.flush()
        customer_notification = BookingNotification(
            source_event_id=event.id,
            booking_id=booking.id,
            customer_id=customers["b"].id,
            event_type="requested",
            title="Booking update",
            message="This update belongs to customer B.",
        )
        mismatched_notification = BookingNotification(
            source_event_id=mismatched_event.id,
            booking_id=booking.id,
            customer_id=customers["a"].id,
            event_type="requested",
            title="Incorrectly linked update",
            message="The linked booking belongs to customer B.",
        )
        db.add_all([customer_notification, mismatched_notification])
        db.flush()
        for key, user in customers.items():
            token = secrets.token_urlsafe(32)
            csrf_token = secrets.token_urlsafe(32)
            tokens[key] = (token, csrf_token)
            db.add(
                AuthSession(
                    user_id=user.id,
                    token_hash=hash_token(token),
                    csrf_token_hash=hashlib.sha256(csrf_token.encode()).hexdigest(),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
        db.commit()
        ids = {
            "customer_a": customers["a"].id,
            "customer_b": customers["b"].id,
            "blocked_customer": customers["blocked"].id,
            "booking": booking.id,
            "vehicle": vehicle.id,
            "pickup_location": location.id,
            "mismatched_notification": mismatched_notification.id,
        }

    yield factory, tokens, ids
    app.dependency_overrides.clear()
    engine.dispose()


def customer_client(tokens: dict[str, tuple[str, str]], key: str) -> TestClient:
    client = TestClient(app, client=("127.0.0.1", 50000))
    token, csrf_token = tokens[key]
    client.cookies.set(CUSTOMER_SESSION_COOKIE, token)
    client.cookies.set(CUSTOMER_CSRF_COOKIE, csrf_token)
    return client


def booking_payload(ids: dict[str, UUID]) -> dict[str, object]:
    start = datetime.now(UTC) + timedelta(days=10)
    return {
        "vehicle_id": str(ids["vehicle"]),
        "pickup_location_id": str(ids["pickup_location"]),
        "start_at": start.isoformat(),
        "end_at": (start + timedelta(days=1)).isoformat(),
        "rental_type": "daily",
        "driving_mode": "self_drive",
    }


def test_anonymous_browser_cannot_read_or_create_customer_bookings(customer_security_app):
    factory, _, ids = customer_security_app
    anonymous = TestClient(app, client=("127.0.0.1", 50001))
    before = None
    with factory() as db:
        before = db.scalar(select(func.count()).select_from(Booking))

    current_user = anonymous.get("/api/v1/auth/me")
    booking_list = anonymous.get("/api/v1/bookings/me")
    booking_create = anonymous.post(
        "/api/v1/bookings",
        json=booking_payload(ids),
    )

    assert current_user.status_code == 401
    assert booking_list.status_code == 401
    assert booking_create.status_code == 401
    with factory() as db:
        after = db.scalar(select(func.count()).select_from(Booking))
    assert after == before


def test_copying_protected_booking_url_to_browser_without_customer_cookie_requires_login(
    customer_security_app,
):
    _, tokens, ids = customer_security_app
    owner = customer_client(tokens, "b")
    protected_url = f"/api/v1/bookings/{ids['booking']}"
    assert owner.get(protected_url).status_code == 200

    separate_browser = TestClient(app, client=("192.0.2.20", 50001))
    copied_url_response = separate_browser.get(protected_url)

    assert copied_url_response.status_code == 401


def test_booking_and_nested_payment_access_is_limited_to_owner(customer_security_app):
    _, tokens, ids = customer_security_app
    customer_a = customer_client(tokens, "a")
    customer_b = customer_client(tokens, "b")
    booking_url = f"/api/v1/bookings/{ids['booking']}"

    denied_detail = customer_a.get(booking_url)
    denied_cancel = customer_a.post(
        f"{booking_url}/cancel",
        json={"note": "Cross-customer request"},
        headers={"X-CSRF-Token": tokens["a"][1]},
    )
    owner_detail = customer_b.get(booking_url)

    assert denied_detail.status_code == 404
    assert denied_cancel.status_code == 404
    assert owner_detail.status_code == 200
    assert len(owner_detail.json()["payments"]) == 1
    assert owner_detail.json()["customer_id"] == str(ids["customer_b"])


def test_notification_access_requires_both_notification_and_booking_ownership(
    customer_security_app,
):
    _, tokens, ids = customer_security_app
    customer_a = customer_client(tokens, "a")
    customer_b = customer_client(tokens, "b")

    a_notifications = customer_a.get("/api/v1/notifications")
    a_unread = customer_a.get("/api/v1/notifications/unread-count")
    a_mark = customer_a.post(
        f"/api/v1/notifications/{ids['mismatched_notification']}/read",
        json={},
        headers={"X-CSRF-Token": tokens["a"][1]},
    )
    b_notifications = customer_b.get("/api/v1/notifications")

    assert a_notifications.status_code == 200
    assert a_notifications.json() == []
    assert a_unread.json() == {"unread_count": 0}
    assert a_mark.status_code == 404
    assert b_notifications.status_code == 200
    assert len(b_notifications.json()) == 1
    assert b_notifications.json()[0]["booking_id"] == str(ids["booking"])


def test_booking_customer_id_is_ignored_in_favor_of_authenticated_session(
    customer_security_app, monkeypatch
):
    factory, tokens, ids = customer_security_app
    customer_a = customer_client(tokens, "a")
    payload = booking_payload(ids)
    payload["customer_id"] = str(ids["customer_b"])
    monkeypatch.setattr(
        "app.services.bookings.dispatch_booking_emails",
        lambda _db, _booking_id: None,
    )
    with factory() as db:
        before = db.scalar(select(func.count()).select_from(Booking))

    response = customer_a.post(
        "/api/v1/bookings",
        json=payload,
        headers={"X-CSRF-Token": tokens["a"][1]},
    )

    assert response.status_code == 201
    assert response.json()["customer_id"] == str(ids["customer_a"])
    with factory() as db:
        after = db.scalar(select(func.count()).select_from(Booking))
    assert after == before + 1


def test_authenticated_booking_uses_customer_from_session(customer_security_app, monkeypatch):
    _, tokens, ids = customer_security_app
    customer_a = customer_client(tokens, "a")
    monkeypatch.setattr(
        "app.services.bookings.dispatch_booking_emails",
        lambda _db, _booking_id: None,
    )

    response = customer_a.post(
        "/api/v1/bookings",
        json=booking_payload(ids),
        headers={"X-CSRF-Token": tokens["a"][1]},
    )

    assert response.status_code == 201
    assert response.json()["customer_id"] == str(ids["customer_a"])


def test_blocked_and_revoked_sessions_cannot_access_customer_routes(customer_security_app):
    _, tokens, _ = customer_security_app
    blocked = customer_client(tokens, "blocked")
    revoked = customer_client(tokens, "a")
    with customer_security_app[0]() as db:
        session = db.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == hash_token(tokens["a"][0])
            )
        )
        assert session is not None
        session.revoked_at = datetime.now(UTC)
        db.commit()

    for route in ("/api/v1/auth/me", "/api/v1/bookings/me", "/api/v1/notifications"):
        assert blocked.get(route).status_code == 403
        assert revoked.get(route).status_code == 401


def test_customer_session_and_admin_session_cookies_are_not_interchangeable(
    customer_security_app,
):
    _, tokens, _ = customer_security_app
    client = customer_client(tokens, "a")
    client.cookies.set("lnr_admin_session", tokens["a"][0])

    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.get("/api/v1/admin/auth/me").status_code == 401
    assert client.get("/api/v1/admin/dashboard/vehicle-stats").status_code == 401
