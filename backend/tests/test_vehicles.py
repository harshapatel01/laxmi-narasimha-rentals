import html
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.auth import AdminAccount, AuthAuditLog, AuthSession, CustomerProfile, User
from app.models.bookings import (
    Booking,
    BookingEmailJob,
    BookingEvent,
    BookingNotification,
    BookingPayment,
)
from app.models.base import Base
from app.models.vehicles import City, PickupLocation, Vehicle, VehicleCategory, VehicleImage
from app.services.security import hash_token, password_hasher
from app.services.bookings import (
    VerifiedOnlinePayment,
    lock_vehicle,
    process_verified_online_payment,
)
from app.services import booking_notifications
from app.services import whatsapp_cloud


@pytest.fixture
def vehicle_app(monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "vehicle_image_storage_path", str(tmp_path))
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
    with factory() as db:
        admin = AdminAccount(
            username="fleet-admin",
            email="fleet-admin@example.test",
            password_hash=password_hasher.hash("a-secure-local-test-password"),
            totp_secret_encrypted="encrypted-test-value",
            mfa_configured=True,
            role="owner",
        )
        db.add(admin)
        db.flush()
        token = f"{uuid4().hex}{uuid4().hex}"
        csrf = f"{uuid4().hex}{uuid4().hex}"
        db.add(
            AuthSession(
                admin_id=admin.id,
                token_hash=hash_token(token),
                csrf_token_hash=sha256(csrf.encode()).hexdigest(),
                is_mfa_verified=True,
                expires_at=datetime.now(UTC) + timedelta(hours=2),
            )
        )
        customer = User(mobile="+919876543210", status="active")
        db.add(customer)
        db.flush()
        db.add(CustomerProfile(user_id=customer.id))
        customer_token = f"{uuid4().hex}{uuid4().hex}"
        customer_csrf = f"{uuid4().hex}{uuid4().hex}"
        db.add(
            AuthSession(
                user_id=customer.id,
                token_hash=hash_token(customer_token),
                csrf_token_hash=sha256(customer_csrf.encode()).hexdigest(),
                expires_at=datetime.now(UTC) + timedelta(hours=2),
            )
        )
        db.commit()
        customer_id = customer.id
        admin_id = admin.id
        city = City(name="Hyderabad", state="Telangana", is_active=True)
        second_city = City(name="Warangal", state="Telangana", is_active=True)
        category = VehicleCategory(name="Sedan", description="Comfortable city cars")
        db.add_all((city, second_city, category))
        db.flush()
        location = PickupLocation(
            city_id=city.id,
            name="Central Hub",
            address="1 Main Road, Hyderabad",
            is_active=True,
        )
        other_location = PickupLocation(
            city_id=second_city.id,
            name="Warangal Hub",
            address="2 Market Road, Warangal",
            is_active=True,
        )
        db.add_all((location, other_location))
        db.commit()
        ids = {
            "city": city.id,
            "second_city": second_city.id,
            "category": category.id,
            "customer": customer_id,
            "customer_csrf": customer_csrf,
            "location": location.id,
            "other_location": other_location.id,
        }

    client = TestClient(app, client=("127.0.0.1", 50000))
    client.cookies.set("lnr_admin_session", token)
    client.cookies.set("lnr_admin_csrf", csrf)
    client.cookies.set("lnr_customer_session", customer_token)
    client.cookies.set("lnr_customer_csrf", customer_csrf)
    client.headers.update({"X-CSRF-Token": csrf})
    yield client, factory, ids
    app.dependency_overrides.clear()
    engine.dispose()


def vehicle_payload(ids: dict, **overrides) -> dict:
    payload = {
        "vehicle_code": "HYD-001",
        "brand": "Honda",
        "model": "City",
        "variant": "ZX",
        "manufacturing_year": 2024,
        "registration_number": "TS 09 AB 1234",
        "category_id": str(ids["category"]),
        "city_id": str(ids["city"]),
        "pickup_location_id": str(ids["location"]),
        "seating_capacity": 5,
        "fuel_type": "petrol",
        "transmission_type": "automatic",
        "self_drive_enabled": True,
        "with_driver_enabled": True,
        "hourly_rental_enabled": True,
        "daily_rental_enabled": True,
        "custom_trip_enabled": True,
        "hourly_base_price": "250.00",
        "daily_base_price": "1800.00",
        "advance_payment_amount": "500.00",
        "description": "Comfortable sedan.",
    }
    payload.update(overrides)
    return payload


def create_vehicle(client: TestClient, ids: dict, **overrides):
    return client.post("/api/v1/admin/vehicles", json=vehicle_payload(ids, **overrides))


def booking_payload(ids: dict, **overrides) -> dict:
    start = datetime.now(UTC) + timedelta(days=2)
    payload = {
        "vehicle_id": str(ids["vehicle"]),
        "start_at": start.isoformat(),
        "end_at": (start + timedelta(days=1)).isoformat(),
        "rental_type": "daily",
        "driving_mode": "self_drive",
        "customer_notes": "Please call before pickup.",
    }
    payload.update(overrides)
    return payload


def create_customer_booking(client: TestClient, ids: dict, **overrides):
    return client.post(
        "/api/v1/bookings",
        json=booking_payload(ids, **overrides),
        headers={"X-CSRF-Token": ids["customer_csrf"]},
    )


def create_additional_customer_client(factory):
    token = f"{uuid4().hex}{uuid4().hex}"
    csrf = f"{uuid4().hex}{uuid4().hex}"
    with factory() as db:
        customer = User(mobile="+919876543219", status="active")
        db.add(customer)
        db.flush()
        db.add(CustomerProfile(user_id=customer.id, first_name="Second", last_name="Customer"))
        db.add(
            AuthSession(
                user_id=customer.id,
                token_hash=hash_token(token),
                csrf_token_hash=sha256(csrf.encode()).hexdigest(),
                expires_at=datetime.now(UTC) + timedelta(hours=2),
            )
        )
        db.commit()
    client = TestClient(app, client=("127.0.0.1", 50001))
    client.cookies.set("lnr_customer_session", token)
    client.cookies.set("lnr_customer_csrf", csrf)
    return client, csrf


def add_booking_record(
    db: Session,
    ids: dict,
    vehicle_id: UUID,
    *,
    reference: str,
    start_at: datetime,
    end_at: datetime,
    status: str,
    customer_id: UUID | None = None,
) -> Booking:
    booking = Booking(
        reference=reference,
        customer_id=customer_id or ids["customer"],
        vehicle_id=vehicle_id,
        city_id=ids["city"],
        pickup_location_id=ids["location"],
        start_at=start_at,
        end_at=end_at,
        rental_type="daily",
        driving_mode="self_drive",
        estimated_total=Decimal("1800.00"),
        daily_rate_snapshot=Decimal("1800.00"),
        advance_amount=Decimal("500.00"),
        amount_paid=Decimal("0.00"),
        remaining_balance=Decimal("1800.00"),
        status=status,
        payment_status="unpaid",
        licence_verification_status="pending_review",
        expires_at=datetime.now(UTC) + timedelta(days=2),
    )
    db.add(booking)
    return booking


def test_admin_vehicle_api_requires_admin_authorization(vehicle_app):
    _, _, _ = vehicle_app
    unauthenticated = TestClient(app, client=("127.0.0.1", 50000))

    response = unauthenticated.get("/api/v1/admin/vehicles")
    create_response = unauthenticated.post(
        "/api/v1/admin/vehicles",
        json=vehicle_payload(vehicle_app[2]),
    )

    assert response.status_code == 401
    assert create_response.status_code == 401
    activate_response = unauthenticated.post(
        f"/api/v1/admin/vehicles/{uuid4()}/activate",
        headers={"X-CSRF-Token": "missing"},
    )
    assert activate_response.status_code == 401


def test_admin_vehicle_dashboard_counts_current_and_available_vehicles(vehicle_app):
    client, factory, ids = vehicle_app
    anonymous = TestClient(app, client=("127.0.0.1", 50002))
    assert anonymous.get("/api/v1/admin/dashboard/vehicle-stats").status_code == 401

    vehicles = []
    for index in range(1, 10):
        response = create_vehicle(
            client,
            ids,
            vehicle_code=f"STAT-{index:03}",
            registration_number=f"TS09ST{index:04}",
        )
        assert response.status_code == 201
        vehicles.append(response.json())

    assert client.patch(
        f"/api/v1/admin/vehicles/{vehicles[6]['id']}/availability",
        json={"availability_status": "maintenance"},
    ).status_code == 200
    assert client.request(
        "DELETE",
        f"/api/v1/admin/vehicles/{vehicles[7]['id']}",
        json={"password": "a-secure-local-test-password"},
    ).status_code == 200

    now = datetime.now(UTC)
    with factory() as db:
        other_customer = User(mobile="+919876543211", status="active")
        db.add(other_customer)
        db.flush()
        add_booking_record(
            db, ids, UUID(vehicles[0]["id"]), reference="LNR-STAT-RENT",
            start_at=now - timedelta(hours=1), end_at=now + timedelta(hours=1),
            status="confirmed", customer_id=other_customer.id,
        )
        add_booking_record(
            db, ids, UUID(vehicles[0]["id"]), reference="LNR-STAT-RENT2",
            start_at=now - timedelta(minutes=30), end_at=now + timedelta(hours=2),
            status="confirmed",
        )
        add_booking_record(
            db, ids, UUID(vehicles[1]["id"]), reference="LNR-STAT-PENDING",
            start_at=now - timedelta(hours=1), end_at=now + timedelta(hours=1),
            status="pending",
        )
        add_booking_record(
            db, ids, UUID(vehicles[2]["id"]), reference="LNR-STAT-FUTURE",
            start_at=now + timedelta(days=1), end_at=now + timedelta(days=2),
            status="confirmed",
        )
        add_booking_record(
            db, ids, UUID(vehicles[3]["id"]), reference="LNR-STAT-PAST",
            start_at=now - timedelta(days=2), end_at=now - timedelta(days=1),
            status="confirmed",
        )
        add_booking_record(
            db, ids, UUID(vehicles[4]["id"]), reference="LNR-STAT-REJECT",
            start_at=now - timedelta(hours=1), end_at=now + timedelta(hours=1),
            status="rejected",
        )
        add_booking_record(
            db, ids, UUID(vehicles[5]["id"]), reference="LNR-STAT-CANCEL",
            start_at=now - timedelta(hours=1), end_at=now + timedelta(hours=1),
            status="cancelled",
        )
        add_booking_record(
            db, ids, UUID(vehicles[8]["id"]), reference="LNR-STAT-COMPLETE",
            start_at=now - timedelta(hours=2), end_at=now - timedelta(hours=1),
            status="completed",
        )
        db.commit()

    response = client.get("/api/v1/admin/dashboard/vehicle-stats")

    assert response.status_code == 200
    assert response.headers["cache-control"].startswith("private, no-store")
    data = response.json()
    assert data["business_timezone"] == "Asia/Kolkata"
    assert data["fleet_vehicle_count"] == 9
    assert data["currently_on_rent_count"] == 1
    assert [row["vehicle_id"] for row in data["currently_on_rent"]] == [vehicles[0]["id"]]
    rental = data["currently_on_rent"][0]
    assert rental["booking_reference"] == "LNR-STAT-RENT"
    assert rental["customer_mobile"] == "+919876543211"
    assert datetime.fromisoformat(rental["pickup_at"]).tzinfo is not None
    assert datetime.fromisoformat(rental["return_at"]).tzinfo is not None
    assert data["upcoming_booking_count"] == 1
    assert [row["vehicle_id"] for row in data["upcoming_bookings"]] == [vehicles[2]["id"]]
    assert data["upcoming_bookings"][0]["booking_reference"] == "LNR-STAT-FUTURE"
    assert datetime.fromisoformat(
        data["upcoming_bookings"][0]["pickup_at"]
    ).tzinfo is not None
    available_ids = {row["vehicle_id"] for row in data["available_now"]}
    assert data["available_now_count"] == 6
    assert available_ids == {vehicle["id"] for vehicle in vehicles[1:6]} | {vehicles[8]["id"]}
    assert vehicles[0]["id"] not in available_ids
    assert vehicles[6]["id"] not in available_ids
    assert vehicles[7]["id"] not in available_ids
    assert not ({row["vehicle_id"] for row in data["currently_on_rent"]} & available_ids)
    assert all(
        {"city", "category", "pickup_location"} <= row.keys()
        for row in data["available_now"]
    )


def test_two_customers_can_submit_pending_requests_but_only_one_can_be_confirmed(vehicle_app):
    admin_client, factory, ids = vehicle_app
    vehicle = create_vehicle(admin_client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    second_client, second_csrf = create_additional_customer_client(factory)
    start = datetime.now(UTC) + timedelta(days=5)
    end = start + timedelta(hours=4)

    first_request = create_customer_booking(
        admin_client,
        ids,
        start_at=start.isoformat(),
        end_at=end.isoformat(),
        rental_type="hourly",
    )
    second_request = second_client.post(
        "/api/v1/bookings",
        json=booking_payload(
            ids,
            start_at=start.isoformat(),
            end_at=end.isoformat(),
            rental_type="custom_trip",
            custom_trip_details="Airport and city travel",
        ),
        headers={"X-CSRF-Token": second_csrf},
    )

    assert first_request.status_code == 201
    assert second_request.status_code == 201
    assert first_request.json()["customer_id"] != second_request.json()["customer_id"]
    assert first_request.json()["status"] == second_request.json()["status"] == "pending"

    first_confirmation = admin_client.post(
        f"/api/v1/admin/bookings/{first_request.json()['id']}/confirm",
        json={},
    )
    second_confirmation = admin_client.post(
        f"/api/v1/admin/bookings/{second_request.json()['id']}/confirm",
        json={},
    )
    assert first_confirmation.status_code == 200
    assert second_confirmation.status_code == 409
    assert second_confirmation.json()["detail"] == (
        "This vehicle is unavailable for your selected dates and times."
    )

    unavailable = admin_client.get(
        f"/api/v1/vehicles/{ids['vehicle']}/availability",
        params={
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
            "rental_type": "daily",
            "driving_mode": "self_drive",
        },
    )
    assert unavailable.status_code == 200
    assert unavailable.json()["available"] is False
    assert unavailable.json()["message"] == (
        "This vehicle is unavailable for your selected dates and times."
    )

    blocked_creation = create_customer_booking(
        admin_client,
        ids,
        start_at=start.isoformat(),
        end_at=end.isoformat(),
    )
    assert blocked_creation.status_code == 409


def test_retried_identical_customer_request_does_not_create_duplicate_booking_or_notifications(
    vehicle_app,
):
    client, factory, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    start = datetime.now(UTC) + timedelta(days=6)
    payload = {
        "start_at": start.isoformat(),
        "end_at": (start + timedelta(hours=4)).isoformat(),
        "rental_type": "hourly",
    }

    first = create_customer_booking(client, ids, **payload)
    retry = create_customer_booking(client, ids, **payload)

    assert first.status_code == retry.status_code == 201
    assert first.json()["id"] == retry.json()["id"]
    with factory() as db:
        rows = list(
            db.scalars(
                select(Booking).where(
                    Booking.customer_id == ids["customer"],
                    Booking.vehicle_id == UUID(ids["vehicle"]),
                )
            )
        )
        assert len(rows) == 1
        assert db.scalar(
            select(func.count()).select_from(BookingNotification).where(
                BookingNotification.booking_id == rows[0].id
            )
        ) == 1
        assert db.scalar(
            select(func.count()).select_from(BookingEmailJob).where(
                BookingEmailJob.booking_id == rows[0].id
            )
        ) == 2


@pytest.mark.parametrize("rental_type", ["hourly", "daily", "custom_trip"])
def test_availability_checks_all_supported_rental_types_and_allows_touching_boundary(
    vehicle_app, rental_type
):
    client, factory, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    start = datetime.now(UTC) + timedelta(days=8)
    end = start + timedelta(hours=5)
    request = create_customer_booking(
        client,
        ids,
        start_at=start.isoformat(),
        end_at=end.isoformat(),
        rental_type="daily",
    )
    assert request.status_code == 201
    confirmed = client.post(
        f"/api/v1/admin/bookings/{request.json()['id']}/confirm",
        json={},
    )
    assert confirmed.status_code == 200

    overlapping = client.get(
        f"/api/v1/vehicles/{ids['vehicle']}/availability",
        params={
            "start_at": (start + timedelta(hours=1)).isoformat(),
            "end_at": (end + timedelta(hours=1)).isoformat(),
            "rental_type": rental_type,
            "driving_mode": "self_drive",
        },
    )
    adjacent = client.get(
        f"/api/v1/vehicles/{ids['vehicle']}/availability",
        params={
            "start_at": end.isoformat(),
            "end_at": (end + timedelta(hours=2)).isoformat(),
            "rental_type": rental_type,
            "driving_mode": "self_drive",
        },
    )

    assert overlapping.status_code == 200
    assert overlapping.json()["available"] is False
    assert adjacent.status_code == 200
    assert adjacent.json()["available"] is True
    past_start = datetime.now(UTC) - timedelta(hours=3)
    past_period = client.get(
        f"/api/v1/vehicles/{ids['vehicle']}/availability",
        params={
            "start_at": past_start.isoformat(),
            "end_at": (past_start + timedelta(hours=1)).isoformat(),
            "rental_type": rental_type,
            "driving_mode": "self_drive",
        },
    )
    assert past_period.status_code == 422


def test_admin_can_create_vehicle_and_return_decimal_prices(vehicle_app):
    client, _, ids = vehicle_app

    response = create_vehicle(client, ids)

    assert response.status_code == 201
    body = response.json()
    assert body["vehicle_code"] == "HYD-001"
    assert body["registration_number"] == "TS09AB1234"
    assert body["hourly_base_price"] == "250.00"
    assert body["daily_base_price"] == "1800.00"
    assert body["category_name"] == "Sedan"
    assert body["city_name"] == "Hyderabad"


def test_admin_can_create_city_category_pickup_and_two_seat_motorcycle(vehicle_app):
    client, _, ids = vehicle_app

    city_response = client.post(
        "/api/v1/admin/cities",
        json={"name": "Karimnagar", "state": "Telangana"},
    )
    category_response = client.post(
        "/api/v1/admin/categories",
        json={"name": "Motorcycle", "description": "Two-wheel motorcycle rentals"},
    )

    assert city_response.status_code == 201
    assert category_response.status_code == 201
    city = city_response.json()
    category = category_response.json()
    assert city["name"] in {
        row["name"] for row in client.get("/api/v1/cities").json()
    }
    assert category["name"] in {
        row["name"] for row in client.get("/api/v1/categories").json()
    }

    location_response = client.post(
        "/api/v1/admin/pickup-locations",
        json={
            "city_id": city["id"],
            "name": "Karimnagar Station",
            "address": "10 Main Road, Karimnagar",
            "google_maps_url": None,
        },
    )

    assert location_response.status_code == 201
    location = location_response.json()
    assert location["city_id"] == city["id"]
    assert location["city_name"] == "Karimnagar"
    assert [
        row["id"]
        for row in client.get(
            "/api/v1/admin/pickup-locations",
            params={"city_id": city["id"]},
        ).json()
    ] == [location["id"]]
    assert client.get(
        "/api/v1/admin/pickup-locations",
        params={"city_id": str(ids["city"])},
    ).json()[0]["id"] == str(ids["location"])

    motorcycle = create_vehicle(
        client,
        ids,
        vehicle_code="KNR-BIKE-001",
        brand="Honda",
        model="Activa",
        registration_number="TS02AA1234",
        category_id=category["id"],
        city_id=city["id"],
        pickup_location_id=location["id"],
        seating_capacity=2,
        self_drive_enabled=True,
        with_driver_enabled=False,
        hourly_rental_enabled=False,
        daily_rental_enabled=True,
        custom_trip_enabled=False,
        hourly_base_price=None,
        daily_base_price="500.00",
        advance_payment_amount="200.00",
    )

    assert motorcycle.status_code == 201
    assert motorcycle.json()["seating_capacity"] == 2
    assert motorcycle.json()["category_name"] == "Motorcycle"
    assert motorcycle.json()["daily_rental_enabled"] is True
    assert motorcycle.json()["daily_base_price"] == "500.00"


def test_catalog_mutations_require_valid_admin_csrf(vehicle_app):
    client, _, _ = vehicle_app
    client.headers["X-CSRF-Token"] = "not-the-session-token"

    response = client.post(
        "/api/v1/admin/cities",
        json={"name": "Karimnagar", "state": "Telangana"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "CSRF validation failed."


def test_duplicate_registration_number_is_rejected(vehicle_app):
    client, _, ids = vehicle_app
    assert create_vehicle(client, ids).status_code == 201

    duplicate = create_vehicle(
        client,
        ids,
        vehicle_code="HYD-002",
        registration_number="TS09AB1234",
    )

    assert duplicate.status_code == 409


def test_vehicle_pickup_location_must_belong_to_selected_city(vehicle_app):
    client, _, ids = vehicle_app

    response = create_vehicle(
        client,
        ids,
        city_id=str(ids["second_city"]),
        pickup_location_id=str(ids["location"]),
    )

    assert response.status_code == 422
    assert "belong to the selected city" in response.json()["detail"]


def test_city_category_and_pickup_location_deactivate_reactivate_cycles(vehicle_app):
    client, _, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    assert vehicle.status_code == 201
    vehicle_id = vehicle.json()["id"]

    city_url = f"/api/v1/admin/cities/{ids['city']}"
    category_url = f"/api/v1/admin/categories/{ids['category']}"
    location_url = f"/api/v1/admin/pickup-locations/{ids['location']}"

    for route, public_path, key in (
        (city_url, "/api/v1/cities", "city_id"),
        (category_url, "/api/v1/categories", "category_id"),
        (location_url, "/api/v1/admin/pickup-locations?include_inactive=true", "location"),
    ):
        inactive = client.delete(route)
        assert inactive.status_code == 200
        assert inactive.json()["is_active"] is False
        admin_rows = client.get(
            f"{route.rsplit('/', 1)[0]}?include_inactive=true"
        )
        assert admin_rows.status_code == 200
        if key == "city_id":
            assert str(ids["city"]) not in {
                row["id"] for row in client.get(public_path).json()
            }
        elif key == "category_id":
            assert client.get(public_path).json() == []
        else:
            assert next(
                row for row in client.get(public_path).json()
                if row["id"] == str(ids[key])
            )["is_active"] is False

        assert client.get("/api/v1/vehicles").json() == []
        unavailable = client.get(
            f"/api/v1/vehicles/{vehicle_id}/availability",
            params={
                "start_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
                "end_at": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
                "rental_type": "daily",
                "driving_mode": "self_drive",
            },
        )
        assert unavailable.status_code == 200
        assert unavailable.json()["available"] is False

        if key == "location":
            city_deactivated = client.delete(city_url)
            assert city_deactivated.status_code == 200
            inactive_city_location = client.post(f"{route}/activate")
            assert inactive_city_location.status_code == 409
            reactivated_city = client.post(f"{city_url}/activate")
            assert reactivated_city.status_code == 200
            assert reactivated_city.json()["is_active"] is True
        restored = client.post(f"{route}/activate")
        assert restored.status_code == 200
        assert restored.json()["is_active"] is True
        assert len(client.get("/api/v1/vehicles").json()) == 1


def test_public_vehicle_list_is_the_same_before_and_after_customer_login(vehicle_app):
    client, factory, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    assert vehicle.status_code == 201

    client.cookies.delete("lnr_customer_session")
    before_login = client.get("/api/v1/vehicles")
    assert before_login.status_code == 200
    assert [row["id"] for row in before_login.json()] == [vehicle.json()["id"]]

    token = f"{uuid4().hex}{uuid4().hex}"
    csrf = f"{uuid4().hex}{uuid4().hex}"
    with factory() as db:
        db.add(
            AuthSession(
                user_id=ids["customer"],
                token_hash=hash_token(token),
                csrf_token_hash=sha256(csrf.encode()).hexdigest(),
                expires_at=datetime.now(UTC) + timedelta(hours=2),
            )
        )
        db.commit()
    client.cookies.set("lnr_customer_session", token)
    after_login = client.get("/api/v1/vehicles")

    assert after_login.status_code == 200
    assert after_login.json() == before_login.json()


def test_anonymous_customer_apis_require_backend_session(vehicle_app):
    client, factory, _ = vehicle_app
    assert client.get("/api/v1/auth/me").status_code == 200
    anonymous = TestClient(app, client=("127.0.0.1", 50000))
    protected_gets = (
        "/api/v1/auth/me",
        "/api/v1/bookings/me",
        "/api/v1/notifications",
        "/api/v1/notifications/unread-count",
    )

    responses = [anonymous.get(path) for path in protected_gets]
    profile_update = anonymous.patch(
        "/api/v1/auth/profile",
        json={"first_name": "Anonymous"},
    )

    assert [response.status_code for response in responses] == [401, 401, 401, 401]
    assert profile_update.status_code == 401
    with factory() as db:
        assert db.scalar(select(Booking)) is None
        assert db.scalar(select(BookingNotification)) is None


def test_blocked_customer_cannot_access_customer_private_endpoints(vehicle_app):
    client, _, ids = vehicle_app
    customer_id = str(ids["customer"])
    blocked = client.post(
        f"/api/v1/admin/customers/{customer_id}/block",
        json={"password": "a-secure-local-test-password"},
    )
    assert blocked.status_code == 200

    responses = (
        client.get("/api/v1/auth/me"),
        client.get("/api/v1/bookings/me"),
        client.get("/api/v1/notifications"),
        client.get("/api/v1/notifications/unread-count"),
        client.patch(
            "/api/v1/auth/profile",
            json={"first_name": "Blocked"},
            headers={"X-CSRF-Token": ids["customer_csrf"]},
        ),
    )

    assert [response.status_code for response in responses] == [403, 403, 403, 403, 403]


def test_customer_can_select_only_an_active_pickup_location_in_vehicle_city(vehicle_app):
    client, _, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    added_location = client.post(
        "/api/v1/admin/pickup-locations",
        json={
            "city_id": str(ids["city"]),
            "name": "North Hub",
            "address": "4 North Road, Hyderabad",
        },
    )
    assert added_location.status_code == 201
    location_id = added_location.json()["id"]
    public_locations = client.get(
        "/api/v1/pickup-locations", params={"city": str(ids["city"])}
    )
    assert public_locations.status_code == 200
    assert location_id in {row["id"] for row in public_locations.json()}

    booking = create_customer_booking(
        client,
        ids,
        pickup_location_id=location_id,
    )
    assert booking.status_code == 201
    assert booking.json()["pickup_location_id"] == location_id
    assert booking.json()["pickup_location_name"] == "North Hub"

    wrong_city = create_customer_booking(
        client,
        ids,
        pickup_location_id=str(ids["other_location"]),
        start_at=(datetime.now(UTC) + timedelta(days=5)).isoformat(),
        end_at=(datetime.now(UTC) + timedelta(days=6)).isoformat(),
    )
    assert wrong_city.status_code == 409

    assert client.delete(
        f"/api/v1/admin/pickup-locations/{location_id}"
    ).status_code == 200
    inactive_location = create_customer_booking(
        client,
        ids,
        pickup_location_id=location_id,
        start_at=(datetime.now(UTC) + timedelta(days=7)).isoformat(),
        end_at=(datetime.now(UTC) + timedelta(days=8)).isoformat(),
    )
    assert inactive_location.status_code == 409


def test_vehicle_pricing_and_rental_mode_validation(vehicle_app):
    client, _, ids = vehicle_app

    no_hourly_price = create_vehicle(client, ids, hourly_base_price=None)
    negative_advance = create_vehicle(
        client,
        ids,
        vehicle_code="HYD-002",
        registration_number="TS09AB1235",
        advance_payment_amount="-1.00",
    )
    floating_excess_precision = create_vehicle(
        client,
        ids,
        vehicle_code="HYD-003",
        registration_number="TS09AB1236",
        daily_base_price="10.999",
    )

    assert no_hourly_price.status_code == 422
    assert negative_advance.status_code == 422
    assert floating_excess_precision.status_code == 422
    assert Decimal("0.01") > Decimal("0")


def test_public_vehicle_filters_and_city_boundary(vehicle_app):
    client, _, ids = vehicle_app
    first = create_vehicle(client, ids)
    second = create_vehicle(
        client,
        ids,
        vehicle_code="WAR-001",
        registration_number="TS03AB1234",
        city_id=str(ids["second_city"]),
        pickup_location_id=str(ids["other_location"]),
        brand="Maruti",
        model="Baleno",
        fuel_type="diesel",
        self_drive_enabled=False,
        with_driver_enabled=True,
    )
    assert first.status_code == 201
    assert second.status_code == 201
    category_response = client.post(
        "/api/v1/admin/categories",
        json={"name": "Motorcycle", "description": "Two-wheelers"},
    )
    assert category_response.status_code == 201
    motorcycle = create_vehicle(
        client,
        ids,
        vehicle_code="HYD-BIKE-001",
        registration_number="TS09BI1234",
        category_id=category_response.json()["id"],
        brand="Yamaha",
        model="R15",
        seating_capacity=2,
    )
    assert motorcycle.status_code == 201

    hyderabad = client.get(
        "/api/v1/vehicles",
        params={"city": str(ids["city"]), "self_drive": "true"},
    )
    warangal = client.get(
        "/api/v1/vehicles",
        params={"city": str(ids["second_city"]), "fuel_type": "diesel"},
    )
    all_public = client.get("/api/v1/vehicles")
    cars = client.get(
        "/api/v1/vehicles",
        params={"category": str(ids["category"])},
    )
    bikes = client.get(
        "/api/v1/vehicles",
        params={"category": category_response.json()["id"]},
    )

    assert all(
        response.status_code == 200
        for response in (hyderabad, warangal, all_public, cars, bikes)
    )
    assert {vehicle["city_name"] for vehicle in hyderabad.json()} == {"Hyderabad"}
    assert {vehicle["model"] for vehicle in hyderabad.json()} == {"City", "R15"}
    assert [vehicle["city_name"] for vehicle in warangal.json()] == ["Warangal"]
    assert len(all_public.json()) == 3
    assert len(cars.json()) == 2
    assert [vehicle["model"] for vehicle in bikes.json()] == ["R15"]


def test_new_email_customer_can_book_and_keep_existing_user_booking_link(vehicle_app):
    client, factory, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    customer_id = str(ids["customer"])
    request = create_customer_booking(client, ids)

    assert request.status_code == 201
    assert request.json()["customer_id"] == customer_id
    csrf = client.cookies.get("lnr_customer_csrf")
    setup = client.post(
        "/api/v1/auth/credentials",
        json={
            "email": "existing.booking@example.net",
            "password": "a-legacy-booking-password",
            "confirm_password": "a-legacy-booking-password",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert setup.status_code == 200
    assert setup.json()["id"] == customer_id
    history = client.get("/api/v1/bookings/me")
    assert [row["id"] for row in history.json()] == [request.json()["id"]]

    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "existing.booking@example.net",
            "password": "a-legacy-booking-password",
        },
    )
    with factory() as db:
        saved = db.get(Booking, UUID(request.json()["id"]))
        assert saved is not None
        assert str(saved.customer_id) == customer_id
    assert login.status_code == 200
    assert login.json()["id"] == customer_id
    assert [row["id"] for row in client.get("/api/v1/bookings/me").json()] == [
        request.json()["id"]
    ]


def test_maintenance_and_inactive_vehicles_are_not_public(vehicle_app):
    client, factory, ids = vehicle_app
    response = create_vehicle(client, ids)
    vehicle_id = response.json()["id"]
    maintenance = client.patch(
        f"/api/v1/admin/vehicles/{vehicle_id}/availability",
        json={"availability_status": "maintenance"},
    )
    assert maintenance.status_code == 200
    assert client.get("/api/v1/vehicles").json() == []

    available = client.patch(
        f"/api/v1/admin/vehicles/{vehicle_id}/availability",
        json={"availability_status": "available"},
    )
    assert available.status_code == 200
    assert len(client.get("/api/v1/vehicles").json()) == 1

    deactivated = client.request(
        "DELETE",
        f"/api/v1/admin/vehicles/{vehicle_id}",
        json={"password": "a-secure-local-test-password"},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["availability_status"] == "inactive"
    assert client.get("/api/v1/vehicles").json() == []
    admin_rows = client.get("/api/v1/admin/vehicles?include_inactive=true")
    assert any(row["id"] == vehicle_id for row in admin_rows.json())

    activated = client.post(f"/api/v1/admin/vehicles/{vehicle_id}/activate")
    assert activated.status_code == 200
    assert activated.json()["is_active"] is True
    assert activated.json()["availability_status"] == "available"
    assert [row["id"] for row in client.get("/api/v1/vehicles").json()] == [vehicle_id]
    with factory() as db:
        legacy_audits = db.scalars(
            select(AuthAuditLog)
            .where(
                AuthAuditLog.action.in_(("vehicle_deleted", "vehicle_restored")),
            )
            .order_by(AuthAuditLog.created_at)
        ).all()
        legacy_audits = [
            audit for audit in legacy_audits
            if audit.details and audit.details.get("vehicle_id") == vehicle_id
        ]
        assert [audit.action for audit in legacy_audits] == [
            "vehicle_deleted",
            "vehicle_restored",
        ]

    second = create_vehicle(
        client,
        ids,
        vehicle_code="HYD-MAINT-001",
        registration_number="TS09AB1237",
    )
    maintenance_id = second.json()["id"]
    with factory() as db:
        maintenance_vehicle = db.get(Vehicle, UUID(maintenance_id))
        assert maintenance_vehicle is not None
        maintenance_vehicle.is_active = False
        maintenance_vehicle.availability_status = "maintenance"
        db.commit()
    reactivated_maintenance = client.post(
        f"/api/v1/admin/vehicles/{maintenance_id}/activate"
    )
    assert reactivated_maintenance.status_code == 200
    assert reactivated_maintenance.json()["is_active"] is True
    assert reactivated_maintenance.json()["availability_status"] == "maintenance"
    assert len(client.get("/api/v1/vehicles").json()) == 1


def test_admin_customer_search_password_confirmation_and_session_revocation(vehicle_app):
    client, factory, ids = vehicle_app
    customer_id = str(ids["customer"])
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    booking = create_customer_booking(client, ids)
    assert booking.status_code == 201
    confirmed = client.post(
        f"/api/v1/admin/bookings/{booking.json()['id']}/confirm",
        json={"note": "Availability checked."},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    with factory() as db:
        customer = db.get(User, ids["customer"])
        profile = db.scalar(
            select(CustomerProfile).where(
                CustomerProfile.user_id == ids["customer"]
            )
        )
        assert customer is not None
        assert profile is not None
        customer.email = "ravi.customer@example.net"
        customer.password_hash = password_hasher.hash("a-customer-password-123")
        profile.first_name = "Ravi"
        profile.last_name = "Kumar"
        db.commit()

    listing = client.get("/api/v1/admin/customers")
    by_name = client.get("/api/v1/admin/customers", params={"q": "Ravi Kumar"})
    by_email = client.get("/api/v1/admin/customers", params={"q": "RAVI.CUSTOMER"})
    by_mobile = client.get("/api/v1/admin/customers", params={"q": "987 654 3210"})
    assert all(response.status_code == 200 for response in (listing, by_name, by_email, by_mobile))
    assert len(listing.json()) == 1
    assert listing.json()[0]["id"] == customer_id
    assert by_name.json()[0]["full_name"] == "Ravi Kumar"
    assert by_email.json()[0]["id"] == customer_id
    assert by_mobile.json()[0]["id"] == customer_id

    history = client.get(f"/api/v1/admin/customers/{customer_id}/bookings")
    assert history.status_code == 200
    assert [row["id"] for row in history.json()] == [booking.json()["id"]]
    blocked = client.post(
        f"/api/v1/admin/customers/{customer_id}/block",
        json={"password": "a-secure-local-test-password", "reason": "Support review"},
    )
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked"
    assert client.get("/api/v1/auth/me").status_code == 403
    assert client.get("/api/v1/bookings/me").status_code == 403
    assert create_customer_booking(client, ids).status_code == 403
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "ravi.customer@example.net", "password": "a-customer-password-123"},
    )
    assert login.status_code == 403

    no_fresh_password = client.post(
        f"/api/v1/admin/customers/{customer_id}/unblock",
        json={},
    )
    wrong_password = client.post(
        f"/api/v1/admin/customers/{customer_id}/unblock",
        json={"password": "not-the-admin-password"},
    )
    assert no_fresh_password.status_code == 422
    assert wrong_password.status_code == 401
    unblocked = client.post(
        f"/api/v1/admin/customers/{customer_id}/unblock",
        json={"password": "a-secure-local-test-password"},
    )
    assert unblocked.status_code == 200
    assert unblocked.json()["status"] == "active"
    assert client.get("/api/v1/auth/me").status_code == 401
    customer_login = client.post(
        "/api/v1/auth/login",
        json={"email": "ravi.customer@example.net", "password": "a-customer-password-123"},
    )
    assert customer_login.status_code == 200
    assert customer_login.json()["id"] == customer_id
    assert [row["id"] for row in client.get("/api/v1/bookings/me").json()] == [
        booking.json()["id"]
    ]
    with factory() as db:
        audits = db.scalars(
            select(AuthAuditLog).where(
                AuthAuditLog.user_id == ids["customer"],
                AuthAuditLog.action.in_(("customer_blocked", "customer_unblocked")),
            ).order_by(AuthAuditLog.created_at)
        ).all()
        assert [audit.action for audit in audits] == ["customer_blocked", "customer_unblocked"]
        assert all(audit.admin_id is not None for audit in audits)
        assert audits[0].details == {"reason": "Support review"}
        assert all(
            audit.details is None or "password" not in audit.details
            for audit in audits
        )
        saved_booking = db.get(Booking, UUID(booking.json()["id"]))
        assert saved_booking is not None
        assert saved_booking.status == "confirmed"


def test_admin_customer_deactivate_reactivate_and_delete_are_distinct(vehicle_app):
    client, factory, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    assert vehicle.status_code == 201
    ids["vehicle"] = vehicle.json()["id"]
    booking = create_customer_booking(client, ids)
    assert booking.status_code == 201

    with factory() as db:
        customer = db.get(User, ids["customer"])
        profile = db.scalar(
            select(CustomerProfile).where(
                CustomerProfile.user_id == ids["customer"]
            )
        )
        assert customer is not None
        assert profile is not None
        customer.email = "deactivate.customer@example.net"
        customer.password_hash = password_hasher.hash("a-customer-password-123")
        profile.first_name = "Ravi"
        profile.last_name = "Kumar"
        saved_booking = db.get(Booking, UUID(booking.json()["id"]))
        assert saved_booking is not None
        payment = BookingPayment(
            booking_id=saved_booking.id,
            amount=Decimal("100.00"),
            payment_method="cash",
            status="verified",
        )
        db.add(payment)
        db.commit()
        payment_id = payment.id

    unauthenticated = TestClient(app, client=("127.0.0.1", 50002))
    assert unauthenticated.request(
        "DELETE",
        f"/api/v1/admin/customers/{ids['customer']}",
        json={"password": "a-secure-local-test-password"},
    ).status_code == 401
    client.headers["X-CSRF-Token"] = "invalid"
    csrf_rejected = client.request(
        "DELETE",
        f"/api/v1/admin/customers/{ids['customer']}",
        json={"password": "a-secure-local-test-password"},
    )
    assert csrf_rejected.status_code == 403
    client.headers["X-CSRF-Token"] = client.cookies.get("lnr_admin_csrf")

    deactivated = client.post(
        f"/api/v1/admin/customers/{ids['customer']}/deactivate",
        json={"password": "a-secure-local-test-password", "reason": "Account closure"},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["status"] == "deactivated"
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/bookings/me").status_code == 401
    assert create_customer_booking(client, ids).status_code == 401
    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "deactivate.customer@example.net",
            "password": "a-customer-password-123",
        },
    )
    assert login.status_code == 401
    cannot_unblock = client.post(
        f"/api/v1/admin/customers/{ids['customer']}/unblock",
        json={"password": "a-secure-local-test-password"},
    )
    assert cannot_unblock.status_code == 409
    reactivated = client.post(
        f"/api/v1/admin/customers/{ids['customer']}/reactivate",
        json={"password": "a-secure-local-test-password", "reason": "Account restored"},
    )
    assert reactivated.status_code == 200
    assert reactivated.json()["status"] == "active"
    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "deactivate.customer@example.net",
            "password": "a-customer-password-123",
        },
    )
    assert login.status_code == 200

    wrong_delete_password = client.request(
        "DELETE",
        f"/api/v1/admin/customers/{ids['customer']}",
        json={"password": "incorrect"},
    )
    assert wrong_delete_password.status_code == 401
    with factory() as db:
        customer = db.get(User, ids["customer"])
        assert customer is not None
        assert customer.status == "active"

    deleted = client.request(
        "DELETE",
        f"/api/v1/admin/customers/{ids['customer']}",
        json={"password": "a-secure-local-test-password", "reason": "Customer requested deletion"},
    )
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"
    assert client.get("/api/v1/auth/me").status_code == 401
    deleted_login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "deactivate.customer@example.net",
            "password": "a-customer-password-123",
        },
    )
    assert deleted_login.status_code == 401
    cannot_reactivate_deleted = client.post(
        f"/api/v1/admin/customers/{ids['customer']}/reactivate",
        json={"password": "a-secure-local-test-password"},
    )
    assert cannot_reactivate_deleted.status_code == 409

    with factory() as db:
        customer = db.get(User, ids["customer"])
        assert customer is not None
        assert customer.status == "deleted"
        assert db.get(Booking, UUID(booking.json()["id"])) is not None
        assert db.get(BookingPayment, payment_id) is not None
        customer_sessions = db.scalars(
            select(AuthSession).where(AuthSession.user_id == ids["customer"])
        ).all()
        assert customer_sessions
        assert all(session.revoked_at is not None for session in customer_sessions)
        audits = db.scalars(
            select(AuthAuditLog).where(
                AuthAuditLog.user_id == ids["customer"],
                AuthAuditLog.action.in_(
                    ("customer_deactivated", "customer_reactivated", "customer_deleted")
                ),
            ).order_by(AuthAuditLog.created_at)
        ).all()
        assert [audit.action for audit in audits] == [
            "customer_deactivated",
            "customer_reactivated",
            "customer_deleted",
        ]
        assert all(audit.admin_id is not None for audit in audits)
        assert all(audit.created_at is not None for audit in audits)
        assert audits[0].details == {"reason": "Account closure"}
        assert audits[-1].details == {"reason": "Customer requested deletion"}


def test_admin_vehicle_archive_requires_confirmation_and_preserves_history(vehicle_app):
    client, factory, ids = vehicle_app
    created = create_vehicle(client, ids)
    assert created.status_code == 201
    vehicle_id = created.json()["id"]
    ids["vehicle"] = vehicle_id
    booking = create_customer_booking(client, ids)
    assert booking.status_code == 201
    with factory() as db:
        saved_booking = db.get(Booking, UUID(booking.json()["id"]))
        assert saved_booking is not None
        payment = BookingPayment(
            booking_id=saved_booking.id,
            amount=Decimal("100.00"),
            payment_method="cash",
            status="verified",
        )
        db.add(payment)
        db.commit()
        payment_id = payment.id

    with factory() as db:
        admin = db.scalar(select(AdminAccount))
        assert admin is not None
        admin.role = "support"
        db.commit()
    restricted_role = client.post(
        f"/api/v1/admin/vehicles/{vehicle_id}/archive",
        json={"password": "a-secure-local-test-password"},
    )
    assert restricted_role.status_code == 403
    with factory() as db:
        admin = db.scalar(select(AdminAccount))
        assert admin is not None
        admin.role = "owner"
        db.commit()

    legacy_delete_without_password = client.delete(
        f"/api/v1/admin/vehicles/{vehicle_id}"
    )
    assert legacy_delete_without_password.status_code == 422
    availability_archive = client.patch(
        f"/api/v1/admin/vehicles/{vehicle_id}/availability",
        json={"availability_status": "inactive"},
    )
    assert availability_archive.status_code == 409
    edit_archive = client.patch(
        f"/api/v1/admin/vehicles/{vehicle_id}",
        json={"availability_status": "inactive"},
    )
    assert edit_archive.status_code == 409
    with factory() as db:
        vehicle = db.get(Vehicle, UUID(vehicle_id))
        assert vehicle is not None
        assert vehicle.is_active is True

    deactivated = client.post(
        f"/api/v1/admin/vehicles/{vehicle_id}/deactivate",
        json={"password": "a-secure-local-test-password", "reason": "Seasonal pause"},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is True
    assert deactivated.json()["availability_status"] == "inactive"
    assert client.get("/api/v1/vehicles").json() == []
    assert create_customer_booking(client, ids).status_code == 409

    reactivated = client.post(
        f"/api/v1/admin/vehicles/{vehicle_id}/reactivate",
        json={"password": "a-secure-local-test-password", "reason": "Season resumed"},
    )
    assert reactivated.status_code == 200
    assert reactivated.json()["is_active"] is True
    assert reactivated.json()["availability_status"] == "available"
    assert [row["id"] for row in client.get("/api/v1/vehicles").json()] == [vehicle_id]

    unauthenticated = TestClient(app, client=("127.0.0.1", 50003))
    assert unauthenticated.request(
        "DELETE",
        f"/api/v1/admin/vehicles/{vehicle_id}",
        json={"password": "a-secure-local-test-password"},
    ).status_code == 401
    assert unauthenticated.post(
        f"/api/v1/admin/vehicles/{vehicle_id}/archive",
        json={"password": "a-secure-local-test-password"},
    ).status_code == 401
    client.headers["X-CSRF-Token"] = "invalid"
    csrf_rejected = client.post(
        f"/api/v1/admin/vehicles/{vehicle_id}/archive",
        json={"password": "a-secure-local-test-password"},
    )
    assert csrf_rejected.status_code == 403
    client.headers["X-CSRF-Token"] = client.cookies.get("lnr_admin_csrf")

    wrong_password = client.post(
        f"/api/v1/admin/vehicles/{vehicle_id}/archive",
        json={"password": "incorrect"},
    )
    assert wrong_password.status_code == 401
    with factory() as db:
        vehicle = db.get(Vehicle, UUID(vehicle_id))
        assert vehicle is not None
        assert vehicle.is_active is True

    wrong_delete_password = client.request(
        "DELETE",
        f"/api/v1/admin/vehicles/{vehicle_id}",
        json={"password": "incorrect"},
    )
    assert wrong_delete_password.status_code == 401
    with factory() as db:
        vehicle = db.get(Vehicle, UUID(vehicle_id))
        assert vehicle is not None
        assert vehicle.is_active is True

    archived = client.request(
        "DELETE",
        f"/api/v1/admin/vehicles/{vehicle_id}",
        json={"password": "a-secure-local-test-password", "reason": "Fleet retirement"},
    )
    assert archived.status_code == 200
    assert archived.json()["is_active"] is False
    assert archived.json()["availability_status"] == "inactive"
    assert client.get("/api/v1/vehicles").json() == []
    assert client.get(f"/api/v1/vehicles/{vehicle_id}").status_code == 404
    cannot_book = create_customer_booking(client, ids)
    assert cannot_book.status_code == 409
    with factory() as db:
        assert db.get(BookingPayment, payment_id) is not None

    restored = client.post(
        f"/api/v1/admin/vehicles/{vehicle_id}/restore",
        json={"password": "a-secure-local-test-password", "reason": "Fleet update"},
    )
    assert restored.status_code == 200
    assert restored.json()["is_active"] is True
    assert restored.json()["availability_status"] == "available"
    assert [row["id"] for row in client.get("/api/v1/vehicles").json()] == [vehicle_id]

    with factory() as db:
        assert db.get(Booking, UUID(booking.json()["id"])) is not None
        assert db.get(BookingPayment, payment_id) is not None
        audits = db.scalars(
            select(AuthAuditLog)
            .where(
                AuthAuditLog.action.in_(
                    (
                        "vehicle_deactivated",
                        "vehicle_reactivated",
                        "vehicle_deleted",
                        "vehicle_restored",
                    )
                ),
            )
            .order_by(AuthAuditLog.created_at)
        ).all()
        audits = [
            audit for audit in audits
            if audit.details and audit.details.get("vehicle_id") == vehicle_id
        ]
        assert [audit.action for audit in audits] == [
            "vehicle_deactivated",
            "vehicle_reactivated",
            "vehicle_deleted",
            "vehicle_restored",
        ]
        assert all(audit.admin_id is not None for audit in audits)
        assert audits[2].details == {
            "vehicle_id": vehicle_id,
            "reason": "Fleet retirement",
        }
        assert audits[3].details == {
            "vehicle_id": vehicle_id,
            "reason": "Fleet update",
        }


def test_admin_customer_operations_require_admin_and_throttle_bad_passwords(vehicle_app):
    client, _, ids = vehicle_app
    customer_id = str(ids["customer"])
    unauthenticated = TestClient(app, client=("127.0.0.1", 50001))
    assert unauthenticated.get("/api/v1/admin/customers").status_code == 401
    assert unauthenticated.post(
        f"/api/v1/admin/customers/{customer_id}/block",
        json={"password": "a-secure-local-test-password"},
    ).status_code == 401

    client.headers["X-CSRF-Token"] = "invalid"
    csrf_rejected = client.post(
        f"/api/v1/admin/customers/{customer_id}/block",
        json={"password": "a-secure-local-test-password"},
    )
    assert csrf_rejected.status_code == 403
    client.headers["X-CSRF-Token"] = client.cookies.get("lnr_admin_csrf")
    for attempt in range(5):
        response = client.post(
            f"/api/v1/admin/customers/{customer_id}/block",
            json={"password": f"incorrect-password-{attempt}"},
        )
        assert response.status_code == 401
    limited = client.post(
        f"/api/v1/admin/customers/{customer_id}/block",
        json={"password": "a-secure-local-test-password"},
    )
    assert limited.status_code == 429


def png_image_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (4, 4), color="gold").save(buffer, format="PNG")
    return buffer.getvalue()


def test_image_upload_uses_safe_generated_filename_and_auth(vehicle_app):
    client, factory, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    vehicle_id = vehicle.json()["id"]
    image = png_image_bytes()

    response = client.post(
        f"/api/v1/admin/vehicles/{vehicle_id}/images",
        files=[("files", ("../../vehicle.png", image, "image/png"))],
    )

    assert response.status_code == 201
    uploaded = response.json()["images"]
    assert len(uploaded) == 1
    image_path = uploaded[0]["image_path"]
    assert image_path.startswith("/uploads/vehicles/")
    assert ".." not in image_path
    stored = get_settings().vehicle_image_storage_directory / image_path.rsplit("/", 1)[1]
    assert stored.exists()
    assert stored.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    with factory() as db:
        image_record = db.scalar(
            select(VehicleImage).where(VehicleImage.vehicle_id == UUID(vehicle_id))
        )
        assert image_record is not None and image_record.is_primary is True


def test_image_upload_rejects_spoofed_or_invalid_image_content(vehicle_app):
    client, _, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    vehicle_id = vehicle.json()["id"]

    spoofed = client.post(
        f"/api/v1/admin/vehicles/{vehicle_id}/images",
        files=[("files", ("car.png", b"<script>alert(1)</script>", "image/png"))],
    )

    assert spoofed.status_code == 415


def test_image_upload_enforces_size_limit(vehicle_app, monkeypatch):
    client, _, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    monkeypatch.setattr(get_settings(), "vehicle_image_max_bytes", 1024)
    oversized = png_image_bytes() + b"x" * 2048

    response = client.post(
        f"/api/v1/admin/vehicles/{vehicle.json()['id']}/images",
        files=[("files", ("car.png", oversized, "image/png"))],
    )

    assert response.status_code == 413


def test_customer_booking_request_snapshots_price_and_vehicle_details(vehicle_app):
    client, _, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]

    response = create_customer_booking(client, ids)

    assert response.status_code == 201
    booking = response.json()
    assert booking["reference"].startswith("LNR-")
    assert booking["status"] == "pending"
    assert booking["payment_status"] == "unpaid"
    assert booking["estimated_total"] == "1800.00"
    assert booking["advance_amount"] == "500.00"
    assert booking["remaining_balance"] == "1800.00"
    assert booking["pickup_location_name"] == "Central Hub"
    assert booking["licence_verification_status"] == "pending_review"
    history = client.get("/api/v1/bookings/me")
    assert history.json()[0]["id"] == booking["id"]
    assert history.headers["cache-control"].startswith("private, no-store")


def test_admin_booking_search_matches_reference_customer_and_vehicle(vehicle_app):
    client, factory, ids = vehicle_app
    with factory() as db:
        customer = db.get(User, ids["customer"])
        customer.email = "searchable@example.test"
        profile = db.scalar(
            select(CustomerProfile).where(CustomerProfile.user_id == customer.id)
        )
        profile.first_name = "Searchable"
        db.commit()
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    booking = create_customer_booking(client, ids).json()

    for query in ("HYD-001", "searchable@example.test", "9876543210"):
        response = client.get("/api/v1/admin/bookings", params={"search": query})
        assert response.status_code == 200
        assert [row["id"] for row in response.json()] == [booking["id"]]
    assert client.get("/api/v1/admin/bookings", params={"search": "no-match"}).json() == []


def test_customer_booking_notifications_are_private_readable_and_persistent(vehicle_app):
    client, factory, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    booking = create_customer_booking(client, ids).json()
    with factory() as db:
        own = db.scalar(
            select(BookingNotification).where(
                BookingNotification.booking_id == UUID(booking["id"])
            )
        )
        other_customer = User(mobile="+919876543211", status="active")
        db.add(other_customer)
        db.flush()
        other_event = BookingEvent(
            booking_id=UUID(booking["id"]),
            actor_type="system",
            action="requested",
            from_status=None,
            to_status="pending",
        )
        db.add(other_event)
        db.flush()
        other_notification = BookingNotification(
            source_event_id=other_event.id,
            booking_id=UUID(booking["id"]),
            customer_id=other_customer.id,
            event_type="requested",
            title="Private test",
            message="Must not be visible.",
        )
        db.add(other_notification)
        db.commit()
        own_id = own.id
        other_id = other_notification.id

    listed = client.get("/api/v1/notifications")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [str(own_id)]
    assert client.get("/api/v1/notifications/unread-count").json() == {"unread_count": 1}
    with factory() as db:
        own_notification = db.get(BookingNotification, own_id)
        assert own_notification.email_status == "not_configured"
        jobs = list(
            db.scalars(
                select(BookingEmailJob).where(
                    BookingEmailJob.booking_id == UUID(booking["id"])
                )
            )
        )
        assert {(job.recipient_type, job.status) for job in jobs} == {
            ("customer", "not_configured"),
            ("admin", "not_configured"),
        }
    forbidden_read = client.post(
        f"/api/v1/notifications/{other_id}/read",
        headers={"X-CSRF-Token": ids["customer_csrf"]},
    )
    assert forbidden_read.status_code == 404
    marked = client.post(
        f"/api/v1/notifications/{own_id}/read",
        headers={"X-CSRF-Token": ids["customer_csrf"]},
    )
    assert marked.status_code == 200
    assert marked.json()["read_at"] is not None
    assert client.get("/api/v1/notifications/unread-count").json() == {"unread_count": 0}
    assert client.get("/api/v1/notifications").json()[0]["booking_reference"] == booking["reference"]


def test_brevo_email_status_is_persisted_without_duplicate_send(vehicle_app, monkeypatch):
    client, factory, ids = vehicle_app
    settings = get_settings()
    monkeypatch.setattr(settings, "brevo_api_key", "test-api-key")
    monkeypatch.setattr(settings, "brevo_sender_email", "rentals@example.test")
    monkeypatch.setattr(settings, "brevo_sender_name", "LNR test")
    sender = Mock()
    monkeypatch.setattr(booking_notifications, "_send_brevo_email", sender)
    with factory() as db:
        db.get(User, ids["customer"]).email = "customer@example.test"
        db.commit()
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]

    created = create_customer_booking(client, ids)

    assert created.status_code == 201
    with factory() as db:
        notification = db.scalar(
            select(BookingNotification).where(
                BookingNotification.booking_id == UUID(created.json()["id"])
            )
        )
        assert notification.email_status == "accepted_by_provider"
        assert notification.email_attempts == 1
        assert notification.email_sent_at is not None
        notification_id = notification.id
    with factory() as db:
        booking_notifications.dispatch_booking_emails(db, UUID(created.json()["id"]))
    sender.assert_called_once()
    assert client.get("/api/v1/notifications").json()[0]["id"] == str(notification_id)


def test_booking_request_emails_have_independent_customer_and_admin_jobs(
    vehicle_app, monkeypatch
):
    client, factory, ids = vehicle_app
    settings = get_settings()
    monkeypatch.setattr(settings, "brevo_api_key", "test-api-key")
    monkeypatch.setattr(settings, "brevo_sender_email", "rentals@example.test")
    monkeypatch.setattr(settings, "brevo_sender_name", "LNR test")
    monkeypatch.setattr(settings, "booking_admin_email", "bookings@example.test")
    sender = Mock()
    monkeypatch.setattr(booking_notifications, "_send_brevo_email", sender)
    with factory() as db:
        db.get(User, ids["customer"]).email = "customer@example.test"
        db.commit()
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]

    created = create_customer_booking(client, ids)

    assert created.status_code == 201
    assert sender.call_count == 2
    recipients = {call.kwargs["recipient"] for call in sender.call_args_list}
    assert recipients == {"customer@example.test", "bookings@example.test"}
    admin_call = next(
        call for call in sender.call_args_list
        if call.kwargs["recipient"] == "bookings@example.test"
    )
    booking_data = created.json()
    admin_text = admin_call.kwargs["text_content"]
    assert admin_call.kwargs["subject"] == (
        f"New booking request · {booking_data['reference']}"
    )
    assert f"Reference: {booking_data['reference']}" in admin_text
    assert "Customer: Customer" in admin_text
    assert f"Mobile: {booking_data['customer_mobile']}" in admin_text
    assert f"Vehicle: {booking_data['vehicle_name']}" in admin_text
    assert "Category: Sedan" in admin_text
    assert f"Pickup location: {booking_data['pickup_location_name']}" in admin_text
    assert (
        "Pickup: "
        + booking_notifications._format_booking_datetime(
            datetime.fromisoformat(booking_data["start_at"])
        )
    ) in admin_text
    assert (
        "Return: "
        + booking_notifications._format_booking_datetime(
            datetime.fromisoformat(booking_data["end_at"])
        )
    ) in admin_text
    assert "Status: pending" in admin_text
    assert admin_call.kwargs["html_content"] == (
        "<p>" + "<br>".join(
            html.escape(line) for line in admin_text.splitlines()
        ) + "</p>"
    )
    with factory() as db:
        jobs = list(
            db.scalars(
                select(BookingEmailJob).where(
                    BookingEmailJob.booking_id == UUID(created.json()["id"])
                )
            )
        )
        assert {(job.recipient_type, job.status) for job in jobs} == {
            ("customer", "accepted_by_provider"),
            ("admin", "accepted_by_provider"),
        }
        assert len({job.source_event_id for job in jobs}) == 1


def test_brevo_failure_is_recorded_and_only_definite_failures_are_retryable(
    vehicle_app, monkeypatch
):
    client, factory, ids = vehicle_app
    settings = get_settings()
    monkeypatch.setattr(settings, "brevo_api_key", "test-api-key")
    monkeypatch.setattr(settings, "brevo_sender_email", "rentals@example.test")
    monkeypatch.setattr(settings, "brevo_sender_name", "LNR test")
    sender = Mock(side_effect=booking_notifications.HTTPError(
        "https://api.brevo.com/v3/smtp/email", 400, "Invalid sender", None, None
    ))
    monkeypatch.setattr(booking_notifications, "_send_brevo_email", sender)
    with factory() as db:
        db.get(User, ids["customer"]).email = "customer@example.test"
        db.commit()
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    created = create_customer_booking(client, ids).json()
    with factory() as db:
        notification = db.scalar(
            select(BookingNotification).where(
                BookingNotification.booking_id == UUID(created["id"])
            )
        )
        assert notification.email_status == "failed"
        assert notification.email_attempts == 1
        assert "HTTP 400" in notification.email_error
        notification_id = notification.id

    sender.side_effect = None
    retried = client.post(
        f"/api/v1/admin/bookings/notifications/email/{notification_id}/retry",
    )
    assert retried.status_code == 200
    assert retried.json()["email_status"] == "accepted_by_provider"
    assert retried.json()["email_attempts"] == 2
    assert sender.call_count == 2


def test_booking_rejects_bad_dates_and_unsupported_modes(vehicle_app):
    client, _, ids = vehicle_app
    vehicle = create_vehicle(
        client,
        ids,
        vehicle_code="HYD-ONLY-SELF",
        registration_number="TS09AB9991",
        with_driver_enabled=False,
    )
    ids["vehicle"] = vehicle.json()["id"]
    start = datetime.now(UTC) + timedelta(days=2)

    invalid_range = create_customer_booking(
        client,
        ids,
        start_at=start.isoformat(),
        end_at=start.isoformat(),
    )
    unsupported_mode = create_customer_booking(
        client,
        ids,
        driving_mode="with_driver",
    )
    naive_datetime = create_customer_booking(
        client,
        ids,
        start_at=(start.replace(tzinfo=None)).isoformat(),
    )

    assert invalid_range.status_code == 422
    assert unsupported_mode.status_code == 422
    assert "not supported" in unsupported_mode.json()["detail"]
    assert naive_datetime.status_code == 422


def test_customer_and_admin_authorization_for_booking_confirmation(vehicle_app):
    client, _, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    booking = create_customer_booking(client, ids).json()
    unauthenticated = TestClient(app, client=("127.0.0.1", 50000))

    forbidden = unauthenticated.post(
        f"/api/v1/admin/bookings/{booking['id']}/confirm",
        json={},
    )
    confirmed = client.post(
        f"/api/v1/admin/bookings/{booking['id']}/confirm",
        json={"note": "Availability checked by admin."},
    )

    assert forbidden.status_code == 401
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    assert confirmed.json()["confirmation_method"] == "admin_manual"
    assert confirmed.json()["confirmed_by_admin_id"] is not None
    assert confirmed.json()["confirmation_note"] == "Availability checked by admin."
    noted = client.patch(
        f"/api/v1/admin/bookings/{booking['id']}/notes",
        json={"admin_notes": "Customer called to reconfirm pickup."},
    )
    assert noted.status_code == 200
    details = client.get(f"/api/v1/admin/bookings/{booking['id']}").json()
    assert details["admin_notes"] == "Customer called to reconfirm pickup."
    assert any(event["action"] == "admin_note_updated" for event in details["events"])


def test_anonymous_booking_cannot_mutate_booking_or_notification_data(vehicle_app):
    client, factory, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    anonymous = TestClient(app, client=("127.0.0.1", 50000))

    response = create_customer_booking(anonymous, ids)

    assert response.status_code == 401
    with factory() as db:
        assert db.scalar(select(Booking).where(Booking.vehicle_id == UUID(ids["vehicle"]))) is None
        assert db.scalar(select(BookingNotification)) is None
        assert db.scalar(select(BookingEmailJob)) is None


def test_booking_uses_authenticated_customer_and_hides_admin_notes(vehicle_app):
    client, factory, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    payload = booking_payload(ids)
    payload["customer_id"] = str(uuid4())

    created = client.post(
        "/api/v1/bookings",
        json=payload,
        headers={"X-CSRF-Token": ids["customer_csrf"]},
    )

    assert created.status_code == 201
    booking = created.json()
    assert booking["customer_id"] == str(ids["customer"])
    foreign_token = f"{uuid4().hex}{uuid4().hex}"
    foreign_csrf = f"{uuid4().hex}{uuid4().hex}"
    with factory() as db:
        foreign_customer = User(mobile="+919876543212", status="active")
        db.add(foreign_customer)
        db.flush()
        db.add(
            AuthSession(
                user_id=foreign_customer.id,
                token_hash=hash_token(foreign_token),
                csrf_token_hash=sha256(foreign_csrf.encode()).hexdigest(),
                expires_at=datetime.now(UTC) + timedelta(hours=2),
            )
        )
        db.commit()
    foreign_client = TestClient(app, client=("127.0.0.1", 50000))
    foreign_client.cookies.set("lnr_customer_session", foreign_token)
    foreign_client.cookies.set("lnr_customer_csrf", foreign_csrf)
    assert foreign_client.get(f"/api/v1/bookings/{booking['id']}").status_code == 404

    confirmation = client.post(
        f"/api/v1/admin/bookings/{booking['id']}/confirm",
        json={"note": "Internal availability check."},
    )
    assert confirmation.status_code == 200
    client.patch(
        f"/api/v1/admin/bookings/{booking['id']}/notes",
        json={"admin_notes": "Internal contact details."},
    )

    customer_detail = client.get(f"/api/v1/bookings/{booking['id']}")

    assert customer_detail.status_code == 200
    assert customer_detail.json()["admin_notes"] is None
    assert customer_detail.json()["confirmation_note"] is None
    assert all(
        event["note"] is None
        for event in customer_detail.json()["events"]
        if event["actor_type"] == "admin"
    )
    with factory() as db:
        saved = db.get(Booking, UUID(booking["id"]))
        assert saved.admin_notes == "Internal contact details."


def test_invalid_customer_csrf_cannot_create_booking(vehicle_app):
    client, factory, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]

    response = client.post(
        "/api/v1/bookings",
        json=booking_payload(ids),
        headers={"X-CSRF-Token": "invalid-csrf-token"},
    )

    assert response.status_code == 403
    with factory() as db:
        assert db.scalar(select(Booking)) is None
        assert db.scalar(select(BookingNotification)) is None
        assert db.scalar(select(BookingEmailJob)) is None


def test_support_admin_cannot_read_or_mutate_bookings_or_email_diagnostics(vehicle_app):
    client, factory, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    booking = create_customer_booking(client, ids).json()
    with factory() as db:
        admin = db.scalar(select(AdminAccount).where(AdminAccount.username == "fleet-admin"))
        admin.role = "support"
        db.commit()

    list_response = client.get("/api/v1/admin/bookings")
    detail_response = client.get(f"/api/v1/admin/bookings/{booking['id']}")
    confirm_response = client.post(
        f"/api/v1/admin/bookings/{booking['id']}/confirm", json={}
    )
    email_response = client.get("/api/v1/admin/bookings/notifications/email-jobs")

    assert list_response.status_code == 403
    assert detail_response.status_code == 403
    assert confirm_response.status_code == 403
    assert email_response.status_code == 403
    with factory() as db:
        assert db.get(Booking, UUID(booking["id"])).status == "pending"


def test_confirmed_overlap_is_rejected_and_repeat_confirmation_is_not_idempotent(vehicle_app):
    client, _, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    first = create_customer_booking(client, ids).json()
    second = create_customer_booking(client, ids).json()

    first_confirmation = client.post(
        f"/api/v1/admin/bookings/{first['id']}/confirm",
        json={},
    )
    overlap_confirmation = client.post(
        f"/api/v1/admin/bookings/{second['id']}/confirm",
        json={},
    )
    duplicate_confirmation = client.post(
        f"/api/v1/admin/bookings/{first['id']}/confirm",
        json={},
    )

    assert first_confirmation.status_code == 200
    assert overlap_confirmation.status_code == 409
    assert duplicate_confirmation.status_code == 409
    assert overlap_confirmation.json()["detail"] == (
        "This vehicle is unavailable for your selected dates and times."
    )


def test_vehicle_confirmation_lock_compiles_to_postgres_row_lock():
    db = Mock()
    db.scalar.return_value = object()

    lock_vehicle(db, uuid4())

    statement = db.scalar.call_args.args[0]
    compiled = str(statement.compile(dialect=postgresql.dialect())).upper()
    assert "FOR UPDATE" in compiled
    assert "VEHICLES" in compiled


def test_admin_can_reject_cancel_complete_and_record_offline_advance(vehicle_app):
    client, _, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    pending = create_customer_booking(client, ids).json()
    offline = client.post(
        f"/api/v1/admin/bookings/{pending['id']}/offline-advance",
        json={
            "amount": "200.00",
            "payment_method": "upi",
            "reference_note": "UPI ref 123",
            "notes": "Received at the front desk.",
            "received_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        },
    )
    assert offline.status_code == 200
    assert offline.json()["payment_status"] == "partial"
    assert offline.json()["amount_paid"] == "200.00"
    completed_advance = client.post(
        f"/api/v1/admin/bookings/{pending['id']}/offline-advance",
        json={"amount": "300.00", "payment_method": "cash"},
    )
    assert completed_advance.status_code == 200
    assert completed_advance.json()["payment_status"] == "offline_paid"
    assert completed_advance.json()["amount_paid"] == "500.00"
    details = client.get(f"/api/v1/admin/bookings/{pending['id']}").json()
    assert any(payment["reference_note"] == "UPI ref 123" for payment in details["payments"])
    assert any(payment["notes"] == "Received at the front desk." for payment in details["payments"])
    assert any(payment["payment_method"] == "upi" and payment["paid_at"] for payment in details["payments"])

    rejected = create_customer_booking(
        client,
        ids,
        start_at=(datetime.now(UTC) + timedelta(days=4)).isoformat(),
        end_at=(datetime.now(UTC) + timedelta(days=5)).isoformat(),
    ).json()
    assert client.post(
        f"/api/v1/admin/bookings/{rejected['id']}/reject",
        json={"note": "Vehicle unavailable."},
    ).json()["status"] == "rejected"

    cancelled = create_customer_booking(
        client,
        ids,
        start_at=(datetime.now(UTC) + timedelta(days=6)).isoformat(),
        end_at=(datetime.now(UTC) + timedelta(days=7)).isoformat(),
    ).json()
    assert client.post(
        f"/api/v1/bookings/{cancelled['id']}/cancel",
        json={"note": "Changed plans."},
        headers={"X-CSRF-Token": ids["customer_csrf"]},
    ).json()["status"] == "cancelled"


def test_custom_trip_requires_details_and_is_quoted_by_admin(vehicle_app):
    client, _, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    missing_details = create_customer_booking(
        client,
        ids,
        rental_type="custom_trip",
        custom_trip_details="",
    )
    request = create_customer_booking(
        client,
        ids,
        rental_type="custom_trip",
        custom_trip_details="Airport transfer, 3 hours.",
    )

    assert missing_details.status_code == 422
    assert request.status_code == 201
    assert request.json()["estimated_total"] is None
    quoted = client.post(
        f"/api/v1/admin/bookings/{request.json()['id']}/quotation",
        json={"amount": "2300.00", "note": "Three-hour city transfer."},
    )
    assert quoted.status_code == 200
    assert quoted.json()["estimated_total"] == "2300.00"
    assert quoted.json()["remaining_balance"] == "2300.00"
    detail = client.get(
        f"/api/v1/admin/bookings/{request.json()['id']}"
    ).json()
    assert any(event["action"] == "custom_trip_quotation_set" for event in detail["events"])


def test_manual_booking_is_confirmed_and_audited(vehicle_app):
    client, _, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    response = client.post(
        "/api/v1/admin/bookings/manual",
        json={
            "mobile": "9876543210",
            "vehicle_id": vehicle.json()["id"],
            "start_at": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
            "end_at": (datetime.now(UTC) + timedelta(days=11)).isoformat(),
            "rental_type": "daily",
            "driving_mode": "self_drive",
            "confirmation_note": "Confirmed during phone call.",
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "confirmed"
    assert response.json()["confirmation_method"] == "admin_manual"
    assert response.json()["customer_mobile"] == "+919876543210"


def test_verified_payment_processing_is_idempotent_and_requires_advance(vehicle_app):
    client, factory, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    booking = create_customer_booking(client, ids).json()
    verified = VerifiedOnlinePayment(
        booking_id=UUID(booking["id"]),
        amount=Decimal("200.00"),
        provider="test-provider-verifier",
        provider_reference="verified-event-001",
        idempotency_key="verified-event-001",
    )

    with factory() as db:
        first = process_verified_online_payment(db, verified)
        first_status = first.status
    with factory() as db:
        replay = process_verified_online_payment(db, verified)
    completion = VerifiedOnlinePayment(
        booking_id=UUID(booking["id"]),
        amount=Decimal("300.00"),
        provider="test-provider-verifier",
        provider_reference="verified-event-002",
        idempotency_key="verified-event-002",
    )
    with factory() as db:
        second = process_verified_online_payment(db, completion)
    with factory() as db:
        replay_completion = process_verified_online_payment(db, completion)

    assert first_status == "pending"
    assert replay.status == "pending"
    assert second.status == "confirmed"
    assert replay_completion.status == "confirmed"
    assert second.confirmation_method == "online_advance"
    assert second.amount_paid == Decimal("500.00")
    assert second.payment_status == "online_paid"
    assert len(second.payments) == 2
    assert len(second.events) == 3
    assert "/api/v1/bookings/{booking_id}/pay" not in app.openapi()["paths"]

    start = datetime.now(UTC) + timedelta(days=30)
    other_booking_response = create_customer_booking(
        client,
        ids,
        start_at=start.isoformat(),
        end_at=(start + timedelta(days=1)).isoformat(),
    )
    assert other_booking_response.status_code == 201
    other_booking = other_booking_response.json()
    reused_reference = VerifiedOnlinePayment(
        booking_id=UUID(other_booking["id"]),
        amount=Decimal("200.00"),
        provider="test-provider-verifier",
        provider_reference="verified-event-001",
        idempotency_key="different-idempotency-key",
    )
    with factory() as db, pytest.raises(HTTPException) as conflict:
        process_verified_online_payment(db, reused_reference)
    assert conflict.value.status_code == 409


def test_verified_payment_after_vehicle_is_booked_is_flagged_for_refund(vehicle_app):
    client, factory, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    first = create_customer_booking(client, ids).json()
    second = create_customer_booking(client, ids).json()
    assert client.post(f"/api/v1/admin/bookings/{second['id']}/confirm", json={}).status_code == 200
    verified = VerifiedOnlinePayment(
        booking_id=UUID(first["id"]),
        amount=Decimal("500.00"),
        provider="test-provider-verifier",
        provider_reference="verified-event-002",
        idempotency_key="verified-event-002",
    )

    with factory() as db:
        result = process_verified_online_payment(db, verified)

    assert result.status == "pending"
    assert result.payment_status == "refund_review"
    assert result.amount_paid == Decimal("500.00")
    assert result.payments[0].status == "refund_required"


def configure_whatsapp_booking(settings, monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_access_token", "test-only-access-token")
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "123456789012345")
    monkeypatch.setattr(settings, "whatsapp_admin_phone_number", "+919876543210")
    monkeypatch.setattr(settings, "whatsapp_api_version", "v22.0")
    monkeypatch.setattr(
        settings, "whatsapp_booking_template_name", "lnr_booking_request"
    )
    monkeypatch.setattr(settings, "whatsapp_booking_template_language", "en_US")


def test_new_booking_sends_approved_template_with_booking_details(
    vehicle_app, monkeypatch
):
    client, factory, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    with factory() as db:
        profile = db.scalar(
            select(CustomerProfile).where(
                CustomerProfile.user_id == ids["customer"]
            )
        )
        assert profile is not None
        profile.first_name = "Asha"
        profile.last_name = "Rao"
        db.commit()
    configure_whatsapp_booking(get_settings(), monkeypatch)
    response = Mock()
    monkeypatch.setattr(whatsapp_cloud.httpx, "post", Mock(return_value=response))

    created = create_customer_booking(client, ids)

    assert created.status_code == 201
    call = whatsapp_cloud.httpx.post.call_args
    assert call.args[0] == (
        "https://graph.facebook.com/v22.0/123456789012345/messages"
    )
    assert call.kwargs["headers"] == {
        "Authorization": "Bearer test-only-access-token"
    }
    template = call.kwargs["json"]["template"]
    assert template["name"] == "lnr_booking_request"
    assert template["language"] == {"code": "en_US"}
    parameters = template["components"][0]["parameters"]
    assert len(parameters) == 4
    result = created.json()
    assert [parameter["text"] for parameter in parameters] == [
        result["reference"],
        "Asha Rao | Mobile: +919876543210",
        "Honda City | Category: Sedan",
        (
            f"Pickup location: Central Hub | "
            f"Pickup: {whatsapp_cloud._format_booking_datetime(datetime.fromisoformat(result['start_at']))} | "
            f"Return: {whatsapp_cloud._format_booking_datetime(datetime.fromisoformat(result['end_at']))} | "
            "Status: Pending"
        ),
    ]
    assert "IST" in parameters[3]["text"]
    with factory() as db:
        assert db.get(Booking, UUID(result["id"])) is not None


def test_retried_booking_request_does_not_send_duplicate_whatsapp(
    vehicle_app, monkeypatch
):
    client, _, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    configure_whatsapp_booking(get_settings(), monkeypatch)
    sender = Mock(return_value=Mock())
    monkeypatch.setattr(whatsapp_cloud.httpx, "post", sender)
    start = datetime.now(UTC) + timedelta(days=6)
    payload = {
        "start_at": start.isoformat(),
        "end_at": (start + timedelta(hours=4)).isoformat(),
        "rental_type": "hourly",
    }

    first = create_customer_booking(client, ids, **payload)
    retry = create_customer_booking(client, ids, **payload)

    assert first.status_code == retry.status_code == 201
    assert first.json()["id"] == retry.json()["id"]
    sender.assert_called_once()


def test_booking_request_succeeds_when_whatsapp_provider_fails(
    vehicle_app, monkeypatch
):
    client, factory, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    configure_whatsapp_booking(get_settings(), monkeypatch)
    monkeypatch.setattr(
        whatsapp_cloud.httpx,
        "post",
        Mock(side_effect=whatsapp_cloud.httpx.ConnectError("mock connection failure")),
    )

    created = create_customer_booking(client, ids)

    assert created.status_code == 201
    with factory() as db:
        assert db.get(Booking, UUID(created.json()["id"])) is not None


def test_booking_request_succeeds_when_meta_rejects_whatsapp_template(
    vehicle_app, monkeypatch
):
    client, factory, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    configure_whatsapp_booking(get_settings(), monkeypatch)
    request = whatsapp_cloud.httpx.Request(
        "POST", "https://graph.facebook.com/v22.0/test/messages"
    )
    rejection = whatsapp_cloud.httpx.Response(400, request=request)
    monkeypatch.setattr(whatsapp_cloud.httpx, "post", Mock(return_value=rejection))

    created = create_customer_booking(client, ids)

    assert created.status_code == 201
    with factory() as db:
        assert db.get(Booking, UUID(created.json()["id"])) is not None


def test_booking_request_does_not_fall_back_to_hello_world(
    vehicle_app, monkeypatch
):
    client, _, ids = vehicle_app
    vehicle = create_vehicle(client, ids)
    ids["vehicle"] = vehicle.json()["id"]
    settings = get_settings()
    configure_whatsapp_booking(settings, monkeypatch)
    monkeypatch.setattr(settings, "whatsapp_booking_template_name", None)
    sender = Mock()
    monkeypatch.setattr(whatsapp_cloud.httpx, "post", sender)

    created = create_customer_booking(client, ids)

    assert created.status_code == 201
    sender.assert_not_called()


def test_connectivity_test_uses_only_generic_hello_world_template(
    monkeypatch,
):
    settings = get_settings()
    configure_whatsapp_booking(settings, monkeypatch)
    sender = Mock(return_value=Mock())
    monkeypatch.setattr(whatsapp_cloud.httpx, "post", sender)

    result = whatsapp_cloud.send_whatsapp_connectivity_test()

    assert result.accepted is True
    template = sender.call_args.kwargs["json"]["template"]
    assert template == {
        "name": "hello_world",
        "language": {"code": "en_US"},
    }
