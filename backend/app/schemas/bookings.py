from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RentalType = Literal["hourly", "daily", "custom_trip"]
DrivingMode = Literal["self_drive", "with_driver"]


class BookingCreate(BaseModel):
    vehicle_id: UUID
    pickup_location_id: UUID | None = None
    start_at: datetime
    end_at: datetime
    rental_type: RentalType
    driving_mode: DrivingMode
    customer_notes: str | None = Field(default=None, max_length=4000)
    custom_trip_details: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_request(self):
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("Pickup and return date/time must include a timezone.")
        if self.end_at <= self.start_at:
            raise ValueError("Return date/time must be after pickup date/time.")
        if self.rental_type == "custom_trip" and not (self.custom_trip_details or "").strip():
            raise ValueError("Trip details are required for a custom trip.")
        return self


class BookingResponse(BaseModel):
    id: UUID
    reference: str
    vehicle_id: UUID
    vehicle_name: str
    vehicle_code: str
    customer_id: UUID
    customer_mobile: str
    customer_name: str | None
    city_id: UUID
    city_name: str
    pickup_location_id: UUID
    pickup_location_name: str
    pickup_address: str
    start_at: datetime
    end_at: datetime
    rental_type: str
    driving_mode: str
    estimated_total: Decimal | None
    hourly_rate_snapshot: Decimal | None
    daily_rate_snapshot: Decimal | None
    advance_amount: Decimal
    amount_paid: Decimal
    remaining_balance: Decimal
    status: str
    payment_status: str
    confirmation_method: str | None
    customer_notes: str | None
    admin_notes: str | None
    custom_trip_details: str | None
    licence_verification_status: str
    confirmed_by_admin_id: UUID | None
    confirmation_note: str | None
    expires_at: datetime
    created_at: datetime
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    model_config = ConfigDict(from_attributes=True)


class BookingEventResponse(BaseModel):
    id: UUID
    actor_type: str
    action: str
    from_status: str | None
    to_status: str | None
    note: str | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class BookingPaymentResponse(BaseModel):
    id: UUID
    amount: Decimal
    payment_method: str
    status: str
    provider: str | None
    provider_reference: str | None
    reference_note: str | None
    notes: str | None
    paid_at: datetime | None
    recorded_by_admin_id: UUID | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class BookingDetailResponse(BookingResponse):
    events: list[BookingEventResponse]
    payments: list[BookingPaymentResponse]


class AdminBookingAction(BaseModel):
    note: str | None = Field(default=None, max_length=4000)


class OfflineAdvanceInput(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    payment_method: Literal["cash", "upi", "bank_transfer"]
    received_at: datetime | None = None
    reference_note: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


class WaiveAdvanceInput(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class BookingNotesInput(BaseModel):
    admin_notes: str | None = Field(default=None, max_length=4000)


class BookingQuotationInput(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    note: str | None = Field(default=None, max_length=4000)


class ManualBookingCreate(BaseModel):
    mobile: str = Field(min_length=10, max_length=18)
    vehicle_id: UUID
    start_at: datetime
    end_at: datetime
    rental_type: RentalType
    driving_mode: DrivingMode
    custom_trip_details: str | None = Field(default=None, max_length=4000)
    customer_notes: str | None = Field(default=None, max_length=4000)
    confirmation_note: str | None = Field(default=None, max_length=4000)

    @field_validator("mobile")
    @classmethod
    def normalize_mobile(cls, value: str) -> str:
        from app.schemas.auth import normalize_indian_mobile

        return normalize_indian_mobile(value)

    @model_validator(mode="after")
    def validate_request(self):
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("Pickup and return date/time must include a timezone.")
        if self.end_at <= self.start_at:
            raise ValueError("Return date/time must be after pickup date/time.")
        if self.rental_type == "custom_trip" and not (self.custom_trip_details or "").strip():
            raise ValueError("Trip details are required for a custom trip.")
        return self


class AvailabilityResponse(BaseModel):
    available: bool
    estimated_total: Decimal | None
    advance_amount: Decimal
    hourly_rate: Decimal | None
    daily_rate: Decimal | None
    message: str | None = None
