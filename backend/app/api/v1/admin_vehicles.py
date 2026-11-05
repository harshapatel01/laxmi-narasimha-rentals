import logging
import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.api.v1.dependencies import get_admin_session, get_admin_session_with_csrf
from app.api.v1.vehicles import vehicle_response
from app.core.config import get_settings
from app.db.session import get_db
from app.models.auth import AdminAccount, AuthAuditLog, AuthSession
from app.models.vehicles import City, PickupLocation, Vehicle, VehicleCategory, VehicleImage
from app.schemas.auth import AdminSensitiveActionRequest
from app.schemas.vehicles import (
    CategoryInput,
    CategoryResponse,
    CityInput,
    CityResponse,
    PickupLocationInput,
    PickupLocationResponse,
    VehicleCreate,
    VehicleAvailabilityUpdate,
    VehicleImageUpdate,
    VehicleResponse,
    VehicleUpdate,
)
from app.services.security import password_hasher

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin vehicle management"])
IMAGE_SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff", ".jpg"),
    "image/png": (b"\x89PNG\r\n\x1a\n", ".png"),
    "image/webp": (b"RIFF", ".webp"),
}
MAX_VEHICLE_IMAGES = 10
PASSWORD_FAILURE_WINDOW = timedelta(minutes=15)
MAX_PASSWORD_FAILURES = 5
ADMIN_ROLES = {"owner", "admin", "manager"}


def _integrity_conflict(db: Session, exc: IntegrityError) -> None:
    db.rollback()
    logger.info("Vehicle management uniqueness or reference constraint rejected a write.")
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="A record with the supplied unique value already exists or is still referenced.",
    ) from exc


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _require_vehicle_manager(db: Session, admin_id: UUID | None) -> AdminAccount:
    if admin_id is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    admin = db.get(AdminAccount, admin_id)
    if admin is None or admin.status != "active":
        raise HTTPException(status_code=401, detail="Authentication required.")
    if admin.role not in ADMIN_ROLES:
        raise HTTPException(
            status_code=403,
            detail="This role cannot manage vehicle archiving.",
        )
    return admin


def _verify_admin_password(
    db: Session,
    admin: AdminAccount,
    request: Request,
    password: str,
) -> None:
    now = datetime.now(UTC)
    request_ip = _client_ip(request)
    recent_failures = db.scalar(
        select(func.count())
        .select_from(AuthAuditLog)
        .where(
            AuthAuditLog.action == "admin_vehicle_password_failed",
            or_(
                AuthAuditLog.admin_id == admin.id,
                AuthAuditLog.request_ip == request_ip,
            ),
            AuthAuditLog.created_at >= now - PASSWORD_FAILURE_WINDOW,
        )
    ) or 0
    if recent_failures >= MAX_PASSWORD_FAILURES:
        raise HTTPException(
            status_code=429,
            detail="Too many password confirmation attempts. Try again later.",
        )
    try:
        valid = password_hasher.verify(admin.password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        valid = False
    if not valid:
        db.add(
            AuthAuditLog(
                admin_id=admin.id,
                action="admin_vehicle_password_failed",
                request_ip=request_ip,
            )
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The administrator password is incorrect.",
        )


def _archive_vehicle(
    vehicle_id: UUID,
    payload: AdminSensitiveActionRequest,
    request: Request,
    auth_session: AuthSession,
    db: Session,
    *,
    audit_action: str = "vehicle_archived",
) -> VehicleResponse:
    admin = _require_vehicle_manager(db, auth_session.admin_id)
    _verify_admin_password(db, admin, request, payload.password)
    vehicle = db.scalar(
        select(Vehicle).where(Vehicle.id == vehicle_id).with_for_update()
    )
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    if not vehicle.is_active:
        raise HTTPException(status_code=409, detail="This vehicle is already archived.")

    vehicle.is_active = False
    vehicle.availability_status = "inactive"
    now = datetime.now(UTC)
    db.add(
        AuthAuditLog(
            admin_id=admin.id,
            action=audit_action,
            request_ip=_client_ip(request),
            details={
                "vehicle_id": str(vehicle.id),
                "reason": payload.reason,
            },
            created_at=now,
        )
    )
    db.commit()
    vehicle = db.scalar(_admin_vehicle_query().where(Vehicle.id == vehicle_id))
    if vehicle is None:
        raise HTTPException(status_code=500, detail="Vehicle was archived but could not be reloaded.")
    return vehicle_response(vehicle)


def _ensure_location_city(db: Session, city_id: UUID, location_id: UUID) -> None:
    location = db.get(PickupLocation, location_id)
    city = db.get(City, city_id)
    if city is None or not city.is_active:
        raise HTTPException(status_code=422, detail="Select an active city.")
    if location is None or not location.is_active or location.city_id != city_id:
        raise HTTPException(
            status_code=422,
            detail="Pickup location must be active and belong to the selected city.",
        )


def _validate_references(db: Session, data: VehicleCreate) -> None:
    _ensure_location_city(db, data.city_id, data.pickup_location_id)
    category = db.get(VehicleCategory, data.category_id)
    if category is None or not category.is_active:
        raise HTTPException(status_code=422, detail="Select an active vehicle category.")


def _admin_vehicle_query():
    return select(Vehicle).execution_options(populate_existing=True).options(
        joinedload(Vehicle.city),
        joinedload(Vehicle.category),
        joinedload(Vehicle.pickup_location),
        joinedload(Vehicle.images),
    )


@router.get("/cities", response_model=list[CityResponse])
def list_cities(
    include_inactive: bool = False,
    _session: AuthSession = Depends(get_admin_session),
    db: Session = Depends(get_db),
) -> list[City]:
    query = select(City).order_by(City.name)
    if not include_inactive:
        query = query.where(City.is_active.is_(True))
    return list(db.scalars(query))


@router.post("/cities", response_model=CityResponse, status_code=201)
def create_city(
    payload: CityInput,
    _session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> City:
    city = City(name=payload.name.strip(), state=payload.state.strip())
    db.add(city)
    try:
        db.commit()
    except IntegrityError as exc:
        _integrity_conflict(db, exc)
    db.refresh(city)
    return city


@router.patch("/cities/{city_id}", response_model=CityResponse)
def update_city(
    city_id: UUID,
    payload: CityInput,
    _session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> City:
    city = db.get(City, city_id)
    if city is None:
        raise HTTPException(status_code=404, detail="City not found.")
    city.name = payload.name.strip()
    city.state = payload.state.strip()
    try:
        db.commit()
    except IntegrityError as exc:
        _integrity_conflict(db, exc)
    db.refresh(city)
    return city


@router.delete("/cities/{city_id}", response_model=CityResponse)
def deactivate_city(
    city_id: UUID,
    _session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> City:
    city = db.get(City, city_id)
    if city is None:
        raise HTTPException(status_code=404, detail="City not found.")
    city.is_active = False
    db.commit()
    db.refresh(city)
    return city


@router.post("/cities/{city_id}/activate", response_model=CityResponse)
def activate_city(
    city_id: UUID,
    _session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> City:
    city = db.get(City, city_id)
    if city is None:
        raise HTTPException(status_code=404, detail="City not found.")
    city.is_active = True
    db.commit()
    db.refresh(city)
    return city


@router.get("/categories", response_model=list[CategoryResponse])
def list_categories(
    include_inactive: bool = False,
    _session: AuthSession = Depends(get_admin_session),
    db: Session = Depends(get_db),
) -> list[VehicleCategory]:
    query = select(VehicleCategory).order_by(VehicleCategory.name)
    if not include_inactive:
        query = query.where(VehicleCategory.is_active.is_(True))
    return list(db.scalars(query))


@router.post("/categories", response_model=CategoryResponse, status_code=201)
def create_category(
    payload: CategoryInput,
    _session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> VehicleCategory:
    category = VehicleCategory(name=payload.name.strip(), description=payload.description)
    db.add(category)
    try:
        db.commit()
    except IntegrityError as exc:
        _integrity_conflict(db, exc)
    db.refresh(category)
    return category


@router.patch("/categories/{category_id}", response_model=CategoryResponse)
def update_category(
    category_id: UUID,
    payload: CategoryInput,
    _session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> VehicleCategory:
    category = db.get(VehicleCategory, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found.")
    category.name = payload.name.strip()
    category.description = payload.description
    try:
        db.commit()
    except IntegrityError as exc:
        _integrity_conflict(db, exc)
    db.refresh(category)
    return category


@router.delete("/categories/{category_id}", response_model=CategoryResponse)
def deactivate_category(
    category_id: UUID,
    _session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> VehicleCategory:
    category = db.get(VehicleCategory, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found.")
    category.is_active = False
    db.commit()
    db.refresh(category)
    return category


@router.post("/categories/{category_id}/activate", response_model=CategoryResponse)
def activate_category(
    category_id: UUID,
    _session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> VehicleCategory:
    category = db.get(VehicleCategory, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found.")
    category.is_active = True
    db.commit()
    db.refresh(category)
    return category


def _location_response(location: PickupLocation) -> PickupLocationResponse:
    return PickupLocationResponse(
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


@router.get("/pickup-locations", response_model=list[PickupLocationResponse])
def list_pickup_locations(
    city_id: UUID | None = None,
    include_inactive: bool = False,
    _session: AuthSession = Depends(get_admin_session),
    db: Session = Depends(get_db),
) -> list[PickupLocationResponse]:
    query = select(PickupLocation).options(joinedload(PickupLocation.city)).order_by(PickupLocation.name)
    if city_id:
        query = query.where(PickupLocation.city_id == city_id)
    if not include_inactive:
        query = query.where(PickupLocation.is_active.is_(True))
    return [_location_response(row) for row in db.scalars(query).unique().all()]


@router.post("/pickup-locations", response_model=PickupLocationResponse, status_code=201)
def create_pickup_location(
    payload: PickupLocationInput,
    _session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> PickupLocationResponse:
    city = db.get(City, payload.city_id)
    if city is None or not city.is_active:
        raise HTTPException(status_code=422, detail="Select an active city.")
    location = PickupLocation(
        city_id=payload.city_id,
        name=payload.name.strip(),
        address=payload.address.strip(),
        google_maps_url=payload.google_maps_url,
    )
    db.add(location)
    try:
        db.commit()
    except IntegrityError as exc:
        _integrity_conflict(db, exc)
    db.refresh(location)
    location.city = city
    return _location_response(location)


@router.patch("/pickup-locations/{location_id}", response_model=PickupLocationResponse)
def update_pickup_location(
    location_id: UUID,
    payload: PickupLocationInput,
    _session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> PickupLocationResponse:
    location = db.scalar(
        select(PickupLocation)
        .options(joinedload(PickupLocation.city))
        .where(PickupLocation.id == location_id)
    )
    if location is None:
        raise HTTPException(status_code=404, detail="Pickup location not found.")
    city = db.get(City, payload.city_id)
    if city is None or not city.is_active:
        raise HTTPException(status_code=422, detail="Select an active city.")
    location.city_id = payload.city_id
    location.name = payload.name.strip()
    location.address = payload.address.strip()
    location.google_maps_url = payload.google_maps_url
    try:
        db.commit()
    except IntegrityError as exc:
        _integrity_conflict(db, exc)
    db.refresh(location)
    return _location_response(location)


@router.delete("/pickup-locations/{location_id}", response_model=PickupLocationResponse)
def deactivate_pickup_location(
    location_id: UUID,
    _session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> PickupLocationResponse:
    location = db.scalar(
        select(PickupLocation)
        .options(joinedload(PickupLocation.city))
        .where(PickupLocation.id == location_id)
    )
    if location is None:
        raise HTTPException(status_code=404, detail="Pickup location not found.")
    location.is_active = False
    db.commit()
    db.refresh(location)
    return _location_response(location)


@router.post(
    "/pickup-locations/{location_id}/activate",
    response_model=PickupLocationResponse,
)
def activate_pickup_location(
    location_id: UUID,
    _session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> PickupLocationResponse:
    location = db.scalar(
        select(PickupLocation)
        .options(joinedload(PickupLocation.city))
        .where(PickupLocation.id == location_id)
    )
    if location is None:
        raise HTTPException(status_code=404, detail="Pickup location not found.")
    city = db.get(City, location.city_id)
    if city is None:
        raise HTTPException(status_code=409, detail="The pickup location's city no longer exists.")
    if not city.is_active:
        raise HTTPException(
            status_code=409,
            detail="Activate this pickup location's city before activating the location.",
        )
    location.is_active = True
    db.commit()
    db.refresh(location)
    return _location_response(location)


@router.get("/vehicles", response_model=list[VehicleResponse])
def list_admin_vehicles(
    city_id: UUID | None = None,
    category_id: UUID | None = None,
    availability_status: str | None = Query(
        default=None, pattern="^(available|maintenance|inactive)$"
    ),
    include_inactive: bool = True,
    _session: AuthSession = Depends(get_admin_session),
    db: Session = Depends(get_db),
) -> list[VehicleResponse]:
    query = _admin_vehicle_query().order_by(Vehicle.created_at.desc())
    if city_id:
        query = query.where(Vehicle.city_id == city_id)
    if category_id:
        query = query.where(Vehicle.category_id == category_id)
    if availability_status:
        query = query.where(Vehicle.availability_status == availability_status)
    if not include_inactive:
        query = query.where(Vehicle.is_active.is_(True))
    return [vehicle_response(vehicle) for vehicle in db.scalars(query).unique().all()]


@router.get("/vehicles/{vehicle_id}", response_model=VehicleResponse)
def get_admin_vehicle(
    vehicle_id: UUID,
    _session: AuthSession = Depends(get_admin_session),
    db: Session = Depends(get_db),
) -> VehicleResponse:
    vehicle = db.scalar(_admin_vehicle_query().where(Vehicle.id == vehicle_id))
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    return vehicle_response(vehicle)


@router.post("/vehicles", response_model=VehicleResponse, status_code=201)
def create_vehicle(
    payload: VehicleCreate,
    _session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> VehicleResponse:
    _validate_references(db, payload)
    vehicle = Vehicle(**payload.model_dump())
    db.add(vehicle)
    try:
        db.commit()
    except IntegrityError as exc:
        _integrity_conflict(db, exc)
    vehicle = db.scalar(_admin_vehicle_query().where(Vehicle.id == vehicle.id))
    if vehicle is None:
        raise HTTPException(status_code=500, detail="Vehicle was saved but could not be reloaded.")
    return vehicle_response(vehicle)


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleResponse)
def update_vehicle(
    vehicle_id: UUID,
    payload: VehicleUpdate,
    _session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> VehicleResponse:
    vehicle = db.scalar(_admin_vehicle_query().where(Vehicle.id == vehicle_id))
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    merged = {
        key: getattr(vehicle, key)
        for key in VehicleCreate.model_fields
    }
    merged.update(payload.model_dump(exclude_unset=True))
    validated = VehicleCreate.model_validate(merged)
    if vehicle.is_active and payload.availability_status == "inactive":
        raise HTTPException(
            status_code=409,
            detail="Use the password-confirmed archive action to deactivate a vehicle.",
        )
    _validate_references(db, validated)
    for key, value in validated.model_dump().items():
        setattr(vehicle, key, value)
    try:
        db.commit()
    except IntegrityError as exc:
        _integrity_conflict(db, exc)
    vehicle = db.scalar(_admin_vehicle_query().where(Vehicle.id == vehicle_id))
    if vehicle is None:
        raise HTTPException(status_code=500, detail="Vehicle was updated but could not be reloaded.")
    return vehicle_response(vehicle)


@router.patch("/vehicles/{vehicle_id}/availability", response_model=VehicleResponse)
def update_vehicle_availability(
    vehicle_id: UUID,
    payload: VehicleAvailabilityUpdate,
    _session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> VehicleResponse:
    status_value = payload.availability_status
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    if status_value == "inactive":
        raise HTTPException(
            status_code=409,
            detail="Use the password-confirmed archive action to deactivate a vehicle.",
        )
    if not vehicle.is_active and status_value == "available":
        raise HTTPException(
            status_code=409,
            detail="Use the restore action to reactivate an archived vehicle.",
        )
    vehicle.availability_status = status_value
    db.commit()
    vehicle = db.scalar(_admin_vehicle_query().where(Vehicle.id == vehicle_id))
    if vehicle is None:
        raise HTTPException(status_code=500, detail="Vehicle status was updated but could not be reloaded.")
    return vehicle_response(vehicle)


@router.delete("/vehicles/{vehicle_id}", response_model=VehicleResponse)
def delete_vehicle(
    vehicle_id: UUID,
    payload: AdminSensitiveActionRequest,
    request: Request,
    auth_session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> VehicleResponse:
    return _archive_vehicle(
        vehicle_id,
        payload,
        request,
        auth_session,
        db,
        audit_action="vehicle_deleted",
    )


@router.post("/vehicles/{vehicle_id}/deactivate", response_model=VehicleResponse)
def deactivate_vehicle(
    vehicle_id: UUID,
    payload: AdminSensitiveActionRequest,
    request: Request,
    auth_session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> VehicleResponse:
    admin = _require_vehicle_manager(db, auth_session.admin_id)
    _verify_admin_password(db, admin, request, payload.password)
    vehicle = db.scalar(
        select(Vehicle).where(Vehicle.id == vehicle_id).with_for_update()
    )
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    if not vehicle.is_active:
        raise HTTPException(
            status_code=409,
            detail="Archived vehicles must be restored before they can be deactivated.",
        )
    if vehicle.availability_status == "inactive":
        raise HTTPException(status_code=409, detail="This vehicle is already deactivated.")

    vehicle.availability_status = "inactive"
    now = datetime.now(UTC)
    db.add(
        AuthAuditLog(
            admin_id=admin.id,
            action="vehicle_deactivated",
            request_ip=_client_ip(request),
            details={
                "vehicle_id": str(vehicle.id),
                "reason": payload.reason,
            },
            created_at=now,
        )
    )
    db.commit()
    vehicle = db.scalar(_admin_vehicle_query().where(Vehicle.id == vehicle_id))
    if vehicle is None:
        raise HTTPException(
            status_code=500, detail="Vehicle was deactivated but could not be reloaded."
        )
    return vehicle_response(vehicle)


@router.post("/vehicles/{vehicle_id}/reactivate", response_model=VehicleResponse)
def reactivate_vehicle(
    vehicle_id: UUID,
    payload: AdminSensitiveActionRequest,
    request: Request,
    auth_session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> VehicleResponse:
    admin = _require_vehicle_manager(db, auth_session.admin_id)
    _verify_admin_password(db, admin, request, payload.password)
    vehicle = db.scalar(
        select(Vehicle).where(Vehicle.id == vehicle_id).with_for_update()
    )
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    if not vehicle.is_active or vehicle.availability_status != "inactive":
        raise HTTPException(
            status_code=409,
            detail="Only deactivated vehicles can be reactivated.",
        )

    vehicle.availability_status = "available"
    now = datetime.now(UTC)
    db.add(
        AuthAuditLog(
            admin_id=admin.id,
            action="vehicle_reactivated",
            request_ip=_client_ip(request),
            details={
                "vehicle_id": str(vehicle.id),
                "reason": payload.reason,
            },
            created_at=now,
        )
    )
    db.commit()
    vehicle = db.scalar(_admin_vehicle_query().where(Vehicle.id == vehicle_id))
    if vehicle is None:
        raise HTTPException(
            status_code=500, detail="Vehicle was reactivated but could not be reloaded."
        )
    return vehicle_response(vehicle)


@router.post("/vehicles/{vehicle_id}/activate", response_model=VehicleResponse)
def activate_vehicle(
    vehicle_id: UUID,
    request: Request,
    auth_session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> VehicleResponse:
    _require_vehicle_manager(db, auth_session.admin_id)
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    was_inactive = not vehicle.is_active
    vehicle.is_active = True
    if vehicle.availability_status == "inactive":
        vehicle.availability_status = "available"
    if was_inactive:
        db.add(
            AuthAuditLog(
                admin_id=auth_session.admin_id,
                action="vehicle_restored",
                request_ip=_client_ip(request),
                details={"vehicle_id": str(vehicle.id), "reason": None},
                created_at=datetime.now(UTC),
            )
        )
    db.commit()
    vehicle = db.scalar(_admin_vehicle_query().where(Vehicle.id == vehicle_id))
    if vehicle is None:
        raise HTTPException(status_code=500, detail="Vehicle was activated but could not be reloaded.")
    return vehicle_response(vehicle)


@router.post("/vehicles/{vehicle_id}/archive", response_model=VehicleResponse)
def archive_vehicle(
    vehicle_id: UUID,
    payload: AdminSensitiveActionRequest,
    request: Request,
    auth_session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> VehicleResponse:
    return _archive_vehicle(vehicle_id, payload, request, auth_session, db)


@router.post("/vehicles/{vehicle_id}/restore", response_model=VehicleResponse)
def restore_vehicle(
    vehicle_id: UUID,
    payload: AdminSensitiveActionRequest,
    request: Request,
    auth_session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> VehicleResponse:
    admin = _require_vehicle_manager(db, auth_session.admin_id)
    _verify_admin_password(db, admin, request, payload.password)
    vehicle = db.scalar(
        select(Vehicle).where(Vehicle.id == vehicle_id).with_for_update()
    )
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    if vehicle.is_active:
        raise HTTPException(status_code=409, detail="This vehicle is already active.")

    vehicle.is_active = True
    if vehicle.availability_status == "inactive":
        vehicle.availability_status = "available"
    now = datetime.now(UTC)
    db.add(
        AuthAuditLog(
            admin_id=admin.id,
            action="vehicle_restored",
            request_ip=_client_ip(request),
            details={
                "vehicle_id": str(vehicle.id),
                "reason": payload.reason,
            },
            created_at=now,
        )
    )
    db.commit()
    vehicle = db.scalar(_admin_vehicle_query().where(Vehicle.id == vehicle_id))
    if vehicle is None:
        raise HTTPException(status_code=500, detail="Vehicle was restored but could not be reloaded.")
    return vehicle_response(vehicle)


def _sanitize_image(data: bytes, declared_type: str | None) -> tuple[str, bytes]:
    if not data:
        raise HTTPException(status_code=415, detail="Image file is empty.")
    try:
        image = Image.open(BytesIO(data))
        image_format = image.format
        image.verify()
        image = Image.open(BytesIO(data))
        if image.width < 1 or image.height < 1 or image.width * image.height > 40_000_000:
            raise HTTPException(status_code=413, detail="Image dimensions are too large.")
        expected = {
            "JPEG": ("image/jpeg", ".jpg"),
            "PNG": ("image/png", ".png"),
            "WEBP": ("image/webp", ".webp"),
        }.get(image_format or "")
        if expected is None:
            raise HTTPException(status_code=415, detail="Only valid JPEG, PNG, and WebP images are supported.")
        mime_type, extension = expected
        if declared_type and declared_type.lower() not in {mime_type, "application/octet-stream"}:
            raise HTTPException(status_code=415, detail="Image content does not match its media type.")
        output = BytesIO()
        if image_format == "JPEG":
            image.convert("RGB").save(output, format="JPEG", optimize=True)
        else:
            image.save(output, format=image_format, optimize=True)
        return extension, output.getvalue()
    except HTTPException:
        raise
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise HTTPException(
            status_code=415,
            detail="Only valid JPEG, PNG, and WebP images are supported.",
        ) from exc


def _stored_image_path(image_path: str) -> Path:
    parsed = urlsplit(image_path)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/uploads/vehicles/"):
        raise HTTPException(status_code=400, detail="Stored image path is invalid.")
    root = get_settings().vehicle_image_storage_directory.resolve()
    target = (root / Path(parsed.path).name).resolve()
    if target.parent != root:
        raise HTTPException(status_code=400, detail="Stored image path is invalid.")
    return target


@router.post("/vehicles/{vehicle_id}/images", response_model=VehicleResponse, status_code=201)
async def upload_vehicle_images(
    vehicle_id: UUID,
    files: list[UploadFile] = File(...),
    _session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> VehicleResponse:
    vehicle = db.scalar(_admin_vehicle_query().where(Vehicle.id == vehicle_id))
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    if not files or len(files) > MAX_VEHICLE_IMAGES:
        raise HTTPException(status_code=422, detail=f"Upload between 1 and {MAX_VEHICLE_IMAGES} images.")
    storage = get_settings().vehicle_image_storage_directory
    storage.mkdir(parents=True, exist_ok=True)
    saved_files: list[Path] = []
    starting_order = max((image.display_order for image in vehicle.images), default=-1) + 1
    try:
        for index, upload in enumerate(files):
            data = await upload.read(get_settings().vehicle_image_max_bytes + 1)
            if len(data) > get_settings().vehicle_image_max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Each image must be smaller than {get_settings().vehicle_image_max_bytes} bytes.",
                )
            extension, sanitized_data = _sanitize_image(data, upload.content_type)
            filename = f"{uuid.uuid4().hex}{extension}"
            destination = (storage / filename).resolve()
            if destination.parent != storage.resolve():
                raise HTTPException(status_code=400, detail="Invalid image filename.")
            with destination.open("xb") as image_file:
                image_file.write(sanitized_data)
            saved_files.append(destination)
            db.add(
                VehicleImage(
                    vehicle_id=vehicle_id,
                    image_path=f"/uploads/vehicles/{filename}",
                    is_primary=not vehicle.images and index == 0,
                    display_order=starting_order + index,
                )
            )
        db.commit()
    except HTTPException:
        db.rollback()
        for saved_file in saved_files:
            saved_file.unlink(missing_ok=True)
        raise
    except (OSError, IntegrityError) as exc:
        db.rollback()
        for saved_file in saved_files:
            saved_file.unlink(missing_ok=True)
        logger.exception("Vehicle image upload failed.")
        if isinstance(exc, IntegrityError):
            raise HTTPException(status_code=409, detail="Unable to save vehicle image records.") from exc
        raise HTTPException(status_code=500, detail="Unable to store vehicle images.") from exc
    vehicle = db.scalar(_admin_vehicle_query().where(Vehicle.id == vehicle_id))
    if vehicle is None:
        raise HTTPException(status_code=500, detail="Images were saved but vehicle could not be reloaded.")
    return vehicle_response(vehicle)


@router.patch(
    "/vehicles/{vehicle_id}/images/{image_id}", response_model=VehicleResponse
)
def update_vehicle_image(
    vehicle_id: UUID,
    image_id: UUID,
    payload: VehicleImageUpdate,
    _session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> VehicleResponse:
    image = db.scalar(
        select(VehicleImage).where(
            VehicleImage.id == image_id, VehicleImage.vehicle_id == vehicle_id
        )
    )
    if image is None:
        raise HTTPException(status_code=404, detail="Vehicle image not found.")
    if payload.is_primary is True:
        db.query(VehicleImage).filter(
            VehicleImage.vehicle_id == vehicle_id
        ).update({VehicleImage.is_primary: False})
    for field in payload.model_fields_set:
        setattr(image, field, getattr(payload, field))
    db.commit()
    vehicle = db.scalar(_admin_vehicle_query().where(Vehicle.id == vehicle_id))
    if vehicle is None:
        raise HTTPException(status_code=500, detail="Image was updated but vehicle could not be reloaded.")
    return vehicle_response(vehicle)


@router.delete(
    "/vehicles/{vehicle_id}/images/{image_id}", response_model=VehicleResponse
)
def delete_vehicle_image(
    vehicle_id: UUID,
    image_id: UUID,
    _session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> VehicleResponse:
    image = db.scalar(
        select(VehicleImage).where(
            VehicleImage.id == image_id, VehicleImage.vehicle_id == vehicle_id
        )
    )
    if image is None:
        raise HTTPException(status_code=404, detail="Vehicle image not found.")
    image_path = _stored_image_path(image.image_path)
    db.delete(image)
    db.commit()
    image_path.unlink(missing_ok=True)
    vehicle = db.scalar(_admin_vehicle_query().where(Vehicle.id == vehicle_id))
    if vehicle is None:
        raise HTTPException(status_code=500, detail="Image was deleted but vehicle could not be reloaded.")
    return vehicle_response(vehicle)
