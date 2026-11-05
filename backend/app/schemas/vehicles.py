from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FuelType = Literal["petrol", "diesel", "cng", "electric", "hybrid"]
TransmissionType = Literal["manual", "automatic"]
AvailabilityStatus = Literal["available", "maintenance", "inactive"]


class CityInput(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    state: str = Field(min_length=2, max_length=100)


class CityResponse(CityInput):
    id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PickupLocationInput(BaseModel):
    city_id: UUID
    name: str = Field(min_length=2, max_length=150)
    address: str = Field(min_length=5, max_length=4000)
    google_maps_url: str | None = Field(default=None, max_length=2048)

    @field_validator("google_maps_url")
    @classmethod
    def validate_maps_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Google Maps link must be a valid HTTPS URL.")
        return value


class PickupLocationResponse(PickupLocationInput):
    id: UUID
    city_name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CategoryInput(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=4000)


class CategoryResponse(CategoryInput):
    id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VehicleFields(BaseModel):
    vehicle_code: str = Field(min_length=2, max_length=40)
    brand: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=100)
    variant: str | None = Field(default=None, max_length=100)
    manufacturing_year: int = Field(ge=1900, le=datetime.now().year + 1)
    registration_number: str = Field(min_length=3, max_length=32)
    category_id: UUID
    city_id: UUID
    pickup_location_id: UUID
    seating_capacity: int = Field(ge=1, le=100)
    fuel_type: FuelType
    transmission_type: TransmissionType
    self_drive_enabled: bool = False
    with_driver_enabled: bool = False
    hourly_rental_enabled: bool = False
    daily_rental_enabled: bool = False
    custom_trip_enabled: bool = False
    hourly_base_price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    daily_base_price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    advance_payment_amount: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=10, decimal_places=2)
    description: str | None = Field(default=None, max_length=10000)

    @field_validator("vehicle_code")
    @classmethod
    def normalize_vehicle_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Vehicle code may contain letters, numbers, hyphens, and underscores.")
        return normalized

    @field_validator("registration_number")
    @classmethod
    def normalize_registration_number(cls, value: str) -> str:
        normalized = "".join(value.upper().split())
        if not normalized.replace("-", "").isalnum():
            raise ValueError("Enter a valid registration number.")
        return normalized

    @field_validator("brand", "model", "variant")
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def validate_rental_configuration(self):
        if not self.self_drive_enabled and not self.with_driver_enabled:
            raise ValueError("Enable self-drive, with-driver, or both service modes.")
        if not any((self.hourly_rental_enabled, self.daily_rental_enabled, self.custom_trip_enabled)):
            raise ValueError("Enable at least one rental mode.")
        if self.hourly_rental_enabled and self.hourly_base_price is None:
            raise ValueError("Hourly base price is required when hourly rental is enabled.")
        if not self.hourly_rental_enabled and self.hourly_base_price is not None:
            raise ValueError("Hourly base price must be empty when hourly rental is disabled.")
        if self.daily_rental_enabled and self.daily_base_price is None:
            raise ValueError("Daily base price is required when daily rental is enabled.")
        if not self.daily_rental_enabled and self.daily_base_price is not None:
            raise ValueError("Daily base price must be empty when daily rental is disabled.")
        return self


class VehicleCreate(VehicleFields):
    pass


class VehicleUpdate(BaseModel):
    vehicle_code: str | None = Field(default=None, min_length=2, max_length=40)
    brand: str | None = Field(default=None, min_length=1, max_length=80)
    model: str | None = Field(default=None, min_length=1, max_length=100)
    variant: str | None = Field(default=None, max_length=100)
    manufacturing_year: int | None = Field(default=None, ge=1900, le=datetime.now().year + 1)
    registration_number: str | None = Field(default=None, min_length=3, max_length=32)
    category_id: UUID | None = None
    city_id: UUID | None = None
    pickup_location_id: UUID | None = None
    seating_capacity: int | None = Field(default=None, ge=1, le=100)
    fuel_type: FuelType | None = None
    transmission_type: TransmissionType | None = None
    self_drive_enabled: bool | None = None
    with_driver_enabled: bool | None = None
    hourly_rental_enabled: bool | None = None
    daily_rental_enabled: bool | None = None
    custom_trip_enabled: bool | None = None
    hourly_base_price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    daily_base_price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    advance_payment_amount: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    description: str | None = Field(default=None, max_length=10000)
    availability_status: AvailabilityStatus | None = None

    @field_validator("vehicle_code")
    @classmethod
    def normalize_vehicle_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not normalized.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Vehicle code may contain letters, numbers, hyphens, and underscores.")
        return normalized

    @field_validator("registration_number")
    @classmethod
    def normalize_registration_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = "".join(value.upper().split())
        if not normalized.replace("-", "").isalnum():
            raise ValueError("Enter a valid registration number.")
        return normalized


class VehicleImageResponse(BaseModel):
    id: UUID
    image_path: str
    is_primary: bool
    display_order: int

    model_config = ConfigDict(from_attributes=True)


class VehicleResponse(BaseModel):
    id: UUID
    vehicle_code: str
    brand: str
    model: str
    variant: str | None
    manufacturing_year: int
    registration_number: str
    category_id: UUID
    category_name: str
    city_id: UUID
    city_name: str
    pickup_location_id: UUID
    pickup_location_name: str
    pickup_address: str
    google_maps_url: str | None
    seating_capacity: int
    fuel_type: str
    transmission_type: str
    self_drive_enabled: bool
    with_driver_enabled: bool
    hourly_rental_enabled: bool
    daily_rental_enabled: bool
    custom_trip_enabled: bool
    hourly_base_price: Decimal | None
    daily_base_price: Decimal | None
    advance_payment_amount: Decimal
    description: str | None
    is_active: bool
    availability_status: AvailabilityStatus
    images: list[VehicleImageResponse]
    created_at: datetime
    updated_at: datetime


class VehicleImageUpdate(BaseModel):
    is_primary: bool | None = None
    display_order: int | None = Field(default=None, ge=0, le=10000)


class VehicleAvailabilityUpdate(BaseModel):
    availability_status: AvailabilityStatus
