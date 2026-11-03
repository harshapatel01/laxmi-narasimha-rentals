from fastapi import APIRouter

from app.api.v1.admin_auth import admin_router, auth_router as admin_auth_router
from app.api.v1.bookings import admin_router as admin_bookings_router
from app.api.v1.bookings import router as bookings_router
from app.api.v1.admin_vehicles import router as admin_vehicles_router
from app.api.v1.admin_customers import router as admin_customers_router
from app.api.v1.notifications import admin_router as admin_notifications_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.auth import router as customer_auth_router
from app.api.v1.vehicles import router as vehicles_router
from app.api.v1.whatsapp_webhook import router as whatsapp_webhook_router

api_router = APIRouter()
api_router.include_router(whatsapp_webhook_router)
api_router.include_router(customer_auth_router)
api_router.include_router(admin_auth_router)
api_router.include_router(admin_router)
api_router.include_router(admin_bookings_router)
api_router.include_router(bookings_router)
api_router.include_router(admin_vehicles_router)
api_router.include_router(admin_customers_router)
api_router.include_router(admin_notifications_router)
api_router.include_router(notifications_router)
api_router.include_router(vehicles_router)
