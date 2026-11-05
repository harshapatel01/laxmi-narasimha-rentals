from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class City(Base):
    __tablename__ = "cities"
    __table_args__ = (
        Index("ix_cities_name_state", "name", "state", unique=True),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    pickup_locations: Mapped[list["PickupLocation"]] = relationship(back_populates="city")
    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="city")


class PickupLocation(Base):
    __tablename__ = "pickup_locations"
    __table_args__ = (
        Index("ix_pickup_location_city_name", "city_id", "name", unique=True),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    city_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("cities.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    google_maps_url: Mapped[str | None] = mapped_column(String(2048))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    city: Mapped[City] = relationship(back_populates="pickup_locations")
    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="pickup_location")


class VehicleCategory(Base):
    __tablename__ = "vehicle_categories"
    __table_args__ = (Index("ix_vehicle_categories_name", "name", unique=True),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="category")


class Vehicle(Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        CheckConstraint("manufacturing_year >= 1900", name="ck_vehicle_manufacturing_year"),
        CheckConstraint("seating_capacity > 0", name="ck_vehicle_seating_capacity"),
        CheckConstraint(
            "hourly_base_price IS NULL OR hourly_base_price >= 0",
            name="ck_vehicle_hourly_price_nonnegative",
        ),
        CheckConstraint(
            "daily_base_price IS NULL OR daily_base_price >= 0",
            name="ck_vehicle_daily_price_nonnegative",
        ),
        CheckConstraint(
            "advance_payment_amount >= 0",
            name="ck_vehicle_advance_payment_nonnegative",
        ),
        CheckConstraint(
            "hourly_rental_enabled OR NOT hourly_base_price IS NOT NULL",
            name="ck_vehicle_hourly_price_requires_mode",
        ),
        CheckConstraint(
            "daily_rental_enabled OR NOT daily_base_price IS NOT NULL",
            name="ck_vehicle_daily_price_requires_mode",
        ),
        CheckConstraint(
            "self_drive_enabled OR with_driver_enabled",
            name="ck_vehicle_has_service_mode",
        ),
        CheckConstraint(
            "hourly_rental_enabled OR daily_rental_enabled OR custom_trip_enabled",
            name="ck_vehicle_has_rental_mode",
        ),
        CheckConstraint(
            "availability_status IN ('available', 'maintenance', 'inactive')",
            name="ck_vehicle_availability_status",
        ),
        CheckConstraint(
            "fuel_type IN ('petrol', 'diesel', 'cng', 'electric', 'hybrid')",
            name="ck_vehicle_fuel_type",
        ),
        CheckConstraint(
            "transmission_type IN ('manual', 'automatic')",
            name="ck_vehicle_transmission_type",
        ),
        Index("ix_vehicles_public_filters", "city_id", "category_id", "is_active", "availability_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    vehicle_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    brand: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    variant: Mapped[str | None] = mapped_column(String(100))
    manufacturing_year: Mapped[int] = mapped_column(Integer, nullable=False)
    registration_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    category_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("vehicle_categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    city_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("cities.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    pickup_location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("pickup_locations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    seating_capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    fuel_type: Mapped[str] = mapped_column(String(20), nullable=False)
    transmission_type: Mapped[str] = mapped_column(String(20), nullable=False)
    self_drive_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    with_driver_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    hourly_rental_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    daily_rental_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    custom_trip_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    hourly_base_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    daily_base_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    advance_payment_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    availability_status: Mapped[str] = mapped_column(
        String(20), default="available", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    category: Mapped[VehicleCategory] = relationship(back_populates="vehicles")
    city: Mapped[City] = relationship(back_populates="vehicles")
    pickup_location: Mapped[PickupLocation] = relationship(back_populates="vehicles")
    images: Mapped[list["VehicleImage"]] = relationship(
        back_populates="vehicle", cascade="all, delete-orphan", order_by="VehicleImage.display_order"
    )


class VehicleImage(Base):
    __tablename__ = "vehicle_images"
    __table_args__ = (
        CheckConstraint("display_order >= 0", name="ck_vehicle_image_display_order"),
        Index("ix_vehicle_images_vehicle_order", "vehicle_id", "display_order"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    vehicle_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    image_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    vehicle: Mapped[Vehicle] = relationship(back_populates="images")
