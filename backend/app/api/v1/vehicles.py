from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.models.vehicles import City, PickupLocation, Vehicle, VehicleCategory
from app.schemas.vehicles import (
    CategoryResponse,
    CityResponse,
    PickupLocationResponse,
    VehicleResponse,
)

router = APIRouter(tags=["vehicles"])


def vehicle_response(vehicle: Vehicle) -> VehicleResponse:
    return VehicleResponse(
        id=vehicle.id,
        vehicle_code=vehicle.vehicle_code,
        brand=vehicle.brand,
        model=vehicle.model,
        variant=vehicle.variant,
        manufacturing_year=vehicle.manufacturing_year,
        registration_number=vehicle.registration_number,
        category_id=vehicle.category_id,
        category_name=vehicle.category.name,
        city_id=vehicle.city_id,
        city_name=vehicle.city.name,
        pickup_location_id=vehicle.pickup_location_id,
        pickup_location_name=vehicle.pickup_location.name,
        pickup_address=vehicle.pickup_location.address,
        google_maps_url=vehicle.pickup_location.google_maps_url,
        seating_capacity=vehicle.seating_capacity,
        fuel_type=vehicle.fuel_type,
        transmission_type=vehicle.transmission_type,
        self_drive_enabled=vehicle.self_drive_enabled,
        with_driver_enabled=vehicle.with_driver_enabled,
        hourly_rental_enabled=vehicle.hourly_rental_enabled,
        daily_rental_enabled=vehicle.daily_rental_enabled,
        custom_trip_enabled=vehicle.custom_trip_enabled,
        hourly_base_price=vehicle.hourly_base_price,
        daily_base_price=vehicle.daily_base_price,
        advance_payment_amount=vehicle.advance_payment_amount,
        description=vehicle.description,
        is_active=vehicle.is_active,
        availability_status=vehicle.availability_status,
        images=vehicle.images,
        created_at=vehicle.created_at,
        updated_at=vehicle.updated_at,
    )


@router.get("/cities", response_model=list[CityResponse])
def public_cities(db: Session = Depends(get_db)) -> list[City]:
    return list(
        db.scalars(select(City).where(City.is_active.is_(True)).order_by(City.name))
    )


@router.get("/categories", response_model=list[CategoryResponse])
def public_categories(db: Session = Depends(get_db)) -> list[VehicleCategory]:
    return list(
        db.scalars(
            select(VehicleCategory)
            .where(VehicleCategory.is_active.is_(True))
            .order_by(VehicleCategory.name)
        )
    )


@router.get("/pickup-locations", response_model=list[PickupLocationResponse])
def public_pickup_locations(
    city: UUID,
    db: Session = Depends(get_db),
) -> list[PickupLocationResponse]:
    locations = db.scalars(
        select(PickupLocation)
        .join(PickupLocation.city)
        .options(joinedload(PickupLocation.city))
        .where(
            PickupLocation.city_id == city,
            PickupLocation.is_active.is_(True),
            City.is_active.is_(True),
        )
        .order_by(PickupLocation.name)
    )
    return [
        PickupLocationResponse(
            id=location.id,
            city_id=location.city_id,
            city_name=location.city.name,
            name=location.name,
            address=location.address,
            google_maps_url=location.google_maps_url,
            is_active=location.is_active,
            created_at=location.created_at,
            updated_at=location.updated_at,
        )
        for location in locations
    ]


@router.get("/vehicles", response_model=list[VehicleResponse])
def public_vehicles(
    city: UUID | None = None,
    category: UUID | None = None,
    self_drive: bool | None = None,
    with_driver: bool | None = None,
    fuel_type: str | None = Query(default=None, pattern="^(petrol|diesel|cng|electric|hybrid)$"),
    transmission: str | None = Query(default=None, pattern="^(manual|automatic)$"),
    db: Session = Depends(get_db),
) -> list[VehicleResponse]:
    query = (
        select(Vehicle)
        .join(Vehicle.city)
        .join(Vehicle.category)
        .join(Vehicle.pickup_location)
        .options(
            joinedload(Vehicle.city),
            joinedload(Vehicle.category),
            joinedload(Vehicle.pickup_location),
            joinedload(Vehicle.images),
        )
        .where(
            Vehicle.is_active.is_(True),
            Vehicle.availability_status == "available",
            City.is_active.is_(True),
            VehicleCategory.is_active.is_(True),
            PickupLocation.is_active.is_(True),
        )
    )
    if city is not None:
        query = query.where(Vehicle.city_id == city)
    if category is not None:
        query = query.where(Vehicle.category_id == category)
    if self_drive is not None:
        query = query.where(Vehicle.self_drive_enabled.is_(self_drive))
    if with_driver is not None:
        query = query.where(Vehicle.with_driver_enabled.is_(with_driver))
    if fuel_type is not None:
        query = query.where(Vehicle.fuel_type == fuel_type)
    if transmission is not None:
        query = query.where(Vehicle.transmission_type == transmission)
    vehicles = db.scalars(query.order_by(Vehicle.created_at.desc())).unique().all()
    return [vehicle_response(vehicle) for vehicle in vehicles]


@router.get("/vehicles/{vehicle_id}", response_model=VehicleResponse)
def public_vehicle_detail(vehicle_id: UUID, db: Session = Depends(get_db)) -> VehicleResponse:
    vehicle = db.scalar(
        select(Vehicle)
        .join(Vehicle.city)
        .join(Vehicle.category)
        .join(Vehicle.pickup_location)
        .options(
            joinedload(Vehicle.city),
            joinedload(Vehicle.category),
            joinedload(Vehicle.pickup_location),
            joinedload(Vehicle.images),
        )
        .where(
            Vehicle.id == vehicle_id,
            Vehicle.is_active.is_(True),
            Vehicle.availability_status == "available",
            City.is_active.is_(True),
            VehicleCategory.is_active.is_(True),
            PickupLocation.is_active.is_(True),
        )
    )
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    return vehicle_response(vehicle)
