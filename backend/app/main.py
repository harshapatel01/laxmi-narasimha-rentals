import logging
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.db.session import check_database_connection

settings = get_settings()
logger = logging.getLogger(__name__)


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="API for Laxmi Narasimha Rentals.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
    expose_headers=["X-CSRF-Token"],
)
app.include_router(api_router, prefix=settings.api_v1_prefix)
app.mount(
    "/uploads/vehicles",
    StaticFiles(directory=str(settings.vehicle_image_storage_directory), check_dir=False),
    name="vehicle-images",
)


@app.middleware("http")
async def validate_api_request_origin(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith(
        settings.api_v1_prefix
    ):
        origin = request.headers.get("origin")
        if origin:
            configured = urlsplit(settings.frontend_origin)
            expected_origin = f"{configured.scheme}://{configured.netloc}"
            if origin != expected_origin:
                return JSONResponse(status_code=403, content={"detail": "Request origin is not allowed."})
    response = await call_next(request)
    private_api_prefixes = (
        f"{settings.api_v1_prefix}/auth/",
        f"{settings.api_v1_prefix}/bookings",
        f"{settings.api_v1_prefix}/notifications",
        f"{settings.api_v1_prefix}/admin/bookings",
        f"{settings.api_v1_prefix}/admin/customers",
        f"{settings.api_v1_prefix}/admin/",
    )
    if request.url.path.startswith(private_api_prefixes):
        response.headers["Cache-Control"] = "private, no-store, no-cache, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@app.get(f"{settings.api_v1_prefix}/health/database", tags=["health"])
def database_health_check() -> dict[str, str]:
    try:
        check_database_connection()
    except RuntimeError as exc:
        logger.warning("Database connectivity check failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Database connection unavailable. Check backend/.env and server logs.",
        ) from exc
    return {"status": "ok", "database": settings.db_name}
