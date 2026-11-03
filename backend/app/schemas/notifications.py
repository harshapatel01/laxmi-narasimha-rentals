from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CustomerNotificationResponse(BaseModel):
    id: UUID
    booking_id: UUID
    booking_reference: str
    event_type: str
    title: str
    message: str
    read_at: datetime | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class EmailNotificationResponse(BaseModel):
    id: UUID
    booking_id: UUID
    booking_reference: str
    event_type: str
    email_status: str
    email_attempts: int
    email_error: str | None
    email_last_attempt_at: datetime | None
    email_provider_accepted_at: datetime | None


class BookingEmailJobResponse(BaseModel):
    id: UUID
    booking_id: UUID
    booking_reference: str
    event_type: str
    recipient_type: str
    status: str
    attempts: int
    error: str | None
    last_attempt_at: datetime | None
    provider_accepted_at: datetime | None
