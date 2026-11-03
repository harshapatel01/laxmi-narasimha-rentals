import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.models.auth import CustomerProfile, User
from app.models.base import Base
from app.models.bookings import Booking
from app.models.vehicles import City, PickupLocation, Vehicle, VehicleCategory
from app.services import bookings as booking_service


def test_postgres_serializes_overlapping_booking_confirmations(monkeypatch):
    database_url = os.environ.get("BOOKING_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set BOOKING_TEST_DATABASE_URL to an isolated PostgreSQL *_test database.")

    url = make_url(database_url)
    if not url.drivername.startswith("postgresql") or not (url.database or "").endswith("_test"):
        pytest.fail("BOOKING_TEST_DATABASE_URL must target a PostgreSQL database ending in _test.")

    bootstrap_engine = create_engine(url, pool_pre_ping=True)
    schema = f"booking_concurrency_{uuid4().hex}"
    quoted_schema = f'"{schema}"'
    with bootstrap_engine.begin() as connection:
        connection.exec_driver_sql(f"CREATE SCHEMA {quoted_schema}")

    engine = create_engine(url, pool_pre_ping=True)

    @event.listens_for(engine, "connect")
    def set_isolated_search_path(connection, _record):
        cursor = connection.cursor()
        cursor.execute(f"SET search_path TO {quoted_schema}")
        cursor.close()

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        Base.metadata.create_all(engine)
        with factory() as db:
            city = City(name="Concurrency City", state="Test State")
            category = VehicleCategory(name="Concurrency Category")
            customer_a = User(mobile="+919876543201", status="active")
            customer_b = User(mobile="+919876543202", status="active")
            db.add_all((city, category, customer_a, customer_b))
            db.flush()
            location = PickupLocation(
                city_id=city.id,
                name="Concurrency Pickup",
                address="1 Test Road",
            )
            db.add(location)
            db.flush()
            vehicle = Vehicle(
                vehicle_code="CONCURRENCY-TEST-1",
                brand="Test",
                model="Vehicle",
                manufacturing_year=2025,
                registration_number="TS09CT0001",
                category_id=category.id,
                city_id=city.id,
                pickup_location_id=location.id,
                seating_capacity=5,
                fuel_type="petrol",
                transmission_type="manual",
                self_drive_enabled=True,
                daily_rental_enabled=True,
                daily_base_price=1000,
                advance_payment_amount=100,
                is_active=True,
                availability_status="available",
            )
            db.add(vehicle)
            db.flush()
            db.add_all(
                (
                    CustomerProfile(user_id=customer_a.id),
                    CustomerProfile(user_id=customer_b.id),
                )
            )
            now = datetime.now(UTC)
            start_at = now + timedelta(days=5)
            end_at = start_at + timedelta(hours=4)
            booking_a = Booking(
                reference="LNR-CONCURRENCY-A",
                customer_id=customer_a.id,
                vehicle_id=vehicle.id,
                city_id=city.id,
                pickup_location_id=location.id,
                start_at=start_at,
                end_at=end_at,
                rental_type="daily",
                driving_mode="self_drive",
                estimated_total=1000,
                daily_rate_snapshot=1000,
                advance_amount=100,
                amount_paid=0,
                remaining_balance=1000,
                status="pending",
                payment_status="unpaid",
                licence_verification_status="pending_review",
                expires_at=now + timedelta(days=2),
            )
            booking_b = Booking(
                reference="LNR-CONCURRENCY-B",
                customer_id=customer_b.id,
                vehicle_id=vehicle.id,
                city_id=city.id,
                pickup_location_id=location.id,
                start_at=start_at,
                end_at=end_at,
                rental_type="daily",
                driving_mode="self_drive",
                estimated_total=1000,
                daily_rate_snapshot=1000,
                advance_amount=100,
                amount_paid=0,
                remaining_balance=1000,
                status="pending",
                payment_status="unpaid",
                licence_verification_status="pending_review",
                expires_at=now + timedelta(days=2),
            )
            db.add_all((booking_a, booking_b))
            db.commit()
            booking_ids = (booking_a.id, booking_b.id)

        monkeypatch.setattr(booking_service, "dispatch_booking_emails", lambda *_args: None)
        start_together = Barrier(2)

        def confirm(booking_id):
            with factory() as db:
                start_together.wait(timeout=10)
                try:
                    booking_service.confirm_booking(
                        db,
                        booking_id,
                        admin_id=None,
                        method="admin_manual",
                    )
                except HTTPException as error:
                    return error.status_code
                return 200

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(confirm, booking_ids))

        assert sorted(results) == [200, 409]
        with factory() as db:
            confirmed = list(
                db.scalars(
                    select(Booking).where(
                        Booking.vehicle_id == vehicle.id,
                        Booking.status == "confirmed",
                    )
                )
            )
            assert len(confirmed) == 1
    finally:
        engine.dispose()
        with bootstrap_engine.begin() as connection:
            connection.exec_driver_sql(f"DROP SCHEMA {quoted_schema} CASCADE")
        bootstrap_engine.dispose()
