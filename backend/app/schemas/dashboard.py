from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class CurrentRentalItem(BaseModel):
    vehicle_id: UUID
    vehicle_name: str
    registration_number: str
    customer_name: str
    customer_mobile: str
    booking_reference: str
    pickup_at: datetime
    return_at: datetime


class UpcomingBookingItem(BaseModel):
    vehicle_id: UUID
    vehicle_name: str
    registration_number: str
    customer_name: str
    customer_mobile: str
    booking_reference: str
    pickup_at: datetime
    return_at: datetime


class AvailableVehicleItem(BaseModel):
    vehicle_id: UUID
    vehicle_name: str
    registration_number: str
    city: str
    category: str
    pickup_location: str


class AdminVehicleDashboardResponse(BaseModel):
    as_of: datetime
    business_timezone: str
    fleet_vehicle_count: int
    currently_on_rent_count: int
    currently_on_rent: list[CurrentRentalItem]
    upcoming_booking_count: int
    upcoming_bookings: list[UpcomingBookingItem]
    available_now_count: int
    available_now: list[AvailableVehicleItem]
