import base64
import hashlib
import hmac
import smtplib
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine

from app.api.v1 import auth as auth_routes
from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.auth import (
    AdminAccount,
    AuthAuditLog,
    AuthSession,
    CustomerPasswordResetToken,
    CustomerProfile,
    User,
)
from app.models.base import Base
from app.services.security import encrypt_totp_secret, hash_token, password_hasher


@pytest.fixture
def auth_test_db(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "admin_mfa_required", True)
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def client(auth_test_db):
    with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
        yield test_client


def register_customer(
    client: TestClient,
    *,
    request_headers: dict[str, str] | None = None,
    **overrides,
):
    payload = {
        "full_name": "Test Customer",
        "email": "customer@gmail.com",
        "mobile": "9876543210",
        "password": "a-customer-password-123",
        "confirm_password": "a-customer-password-123",
    }
    payload.update(overrides)
    return client.post("/api/v1/auth/register", json=payload, headers=request_headers)


def configure_reset_smtp(settings, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_username", "smtp-user@example.test")
    monkeypatch.setattr(settings, "smtp_password", "test-only-smtp-password")
    monkeypatch.setattr(settings, "smtp_from_email", "noreply@example.test")
    monkeypatch.setattr(settings, "smtp_use_ssl", False)


def request_password_reset(client: TestClient, email: str):
    return client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": email},
    )


def test_customer_registration_normalizes_mobile_and_creates_secure_session(client, auth_test_db):
    response = register_customer(
        client,
        request_headers={"Origin": get_settings().frontend_origin},
    )

    assert response.status_code == 201
    result = response.json()
    assert result["email"] == "customer@gmail.com"
    assert result["mobile"] == "+919876543210"
    assert result["mobile_verified"] is False
    assert result["first_name"] == "Test"
    assert result["last_name"] == "Customer"
    assert "lnr_customer_session" in response.cookies
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=none" in response.headers["set-cookie"]
    csrf_token = response.cookies["lnr_customer_csrf"]
    assert response.headers["x-csrf-token"] == csrf_token
    assert response.headers["access-control-expose-headers"] == "X-CSRF-Token"
    assert response.headers["cache-control"].startswith("private, no-store")
    current_customer = client.get(
        "/api/v1/auth/me",
        headers={"Origin": get_settings().frontend_origin},
    )
    assert current_customer.json()["id"] == result["id"]
    assert current_customer.headers["x-csrf-token"] == csrf_token
    assert current_customer.headers["cache-control"].startswith("private, no-store")
    with auth_test_db() as db:
        user = db.scalar(select(User).where(User.email == "customer@gmail.com"))
        assert user is not None
        assert user.password_hash is not None
        assert password_hasher.verify(user.password_hash, "a-customer-password-123")


def test_customer_session_cookies_are_secure_outside_local_development(
    client, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "staging")
    monkeypatch.setattr(settings, "secure_cookies", False)

    response = register_customer(client)

    assert response.status_code == 201
    cookie_headers = response.headers.get_list("set-cookie")
    session_cookie = next(header for header in cookie_headers if header.startswith("lnr_customer_session="))
    csrf_cookie = next(header for header in cookie_headers if header.startswith("lnr_customer_csrf="))
    assert "secure" in session_cookie.lower()
    assert "httponly" in session_cookie.lower()
    assert "samesite=none" in session_cookie.lower()
    assert "secure" in csrf_cookie.lower()
    assert "httponly" not in csrf_cookie.lower()
    assert "samesite=none" in csrf_cookie.lower()


def test_customer_session_check_does_not_expose_a_mismatched_csrf_cookie(client):
    assert register_customer(client).status_code == 201
    client.cookies.set("lnr_customer_csrf", "different-session-token")

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert "x-csrf-token" not in response.headers


def test_customer_registration_requires_valid_mobile_and_matching_password(client):
    missing_mobile = register_customer(client, mobile="")
    invalid_mobile = register_customer(client, email="other@example.com", mobile="1234567890")
    mismatch = register_customer(
        client,
        email="mismatch@example.com",
        confirm_password="a-different-password-123",
    )

    assert missing_mobile.status_code == 422
    assert invalid_mobile.status_code == 422
    assert mismatch.status_code == 422


def test_customer_registration_rejects_duplicate_email_and_mobile(client):
    assert register_customer(client).status_code == 201

    duplicate_email = register_customer(client, mobile="9876543211")
    duplicate_mobile = register_customer(client, email="someone.else@example.net")

    assert duplicate_email.status_code == 409
    assert duplicate_mobile.status_code == 409


def test_customer_email_password_login_and_invalid_credentials(client):
    registered = register_customer(client)
    assert registered.status_code == 201
    client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": client.cookies.get("lnr_customer_csrf")},
    )

    invalid = client.post(
        "/api/v1/auth/login",
        json={"email": "customer@gmail.com", "password": "wrong-customer-password"},
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "CUSTOMER@gmail.com", "password": "a-customer-password-123"},
    )

    assert invalid.status_code == 401
    assert login.status_code == 200
    assert login.json()["id"] == registered.json()["id"]
    assert "lnr_customer_session" in login.cookies
    assert client.get("/api/v1/auth/me").status_code == 200


def test_customer_login_rotates_the_presented_session(client, auth_test_db):
    registration = register_customer(client)
    assert registration.status_code == 201
    prior_token = client.cookies.get("lnr_customer_session")

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "customer@gmail.com", "password": "a-customer-password-123"},
    )
    rotated_token = client.cookies.get("lnr_customer_session")

    assert login.status_code == 200
    assert rotated_token != prior_token
    assert client.get("/api/v1/auth/me").status_code == 200
    with auth_test_db() as db:
        prior_session = db.scalar(
            select(AuthSession).where(AuthSession.token_hash == hash_token(prior_token))
        )
        assert prior_session is not None
        assert prior_session.revoked_at is not None
    old_browser = TestClient(app, client=("127.0.0.1", 50000))
    old_browser.cookies.set("lnr_customer_session", prior_token)
    assert old_browser.get("/api/v1/auth/me").status_code == 401


def test_customer_login_revokes_presented_session_when_switching_accounts(
    client, auth_test_db
):
    registration = register_customer(client)
    assert registration.status_code == 201
    prior_token = client.cookies.get("lnr_customer_session")
    prior_csrf = client.cookies.get("lnr_customer_csrf")
    with auth_test_db() as db:
        second_customer = User(
            mobile="+919876543211",
            email="second@example.com",
            password_hash=password_hasher.hash("a-second-customer-password"),
            status="active",
        )
        db.add(second_customer)
        db.commit()

    switched = client.post(
        "/api/v1/auth/login",
        json={
            "email": "second@example.com",
            "password": "a-second-customer-password",
        },
    )
    old_browser = TestClient(app, client=("127.0.0.1", 50000))
    old_browser.cookies.set("lnr_customer_session", prior_token)
    old_browser.cookies.set("lnr_customer_csrf", prior_csrf)

    assert switched.status_code == 200
    assert switched.json()["email"] == "second@example.com"
    assert client.get("/api/v1/auth/me").json()["email"] == "second@example.com"
    assert old_browser.get("/api/v1/auth/me").status_code == 401
    with auth_test_db() as db:
        prior_session = db.scalar(
            select(AuthSession).where(AuthSession.token_hash == hash_token(prior_token))
        )
        assert prior_session is not None
        assert prior_session.revoked_at is not None


def test_same_browser_tabs_share_session_and_logout_revokes_both(client):
    assert register_customer(client).status_code == 201
    token = client.cookies.get("lnr_customer_session")
    csrf = client.cookies.get("lnr_customer_csrf")
    second_tab = TestClient(app, client=("127.0.0.1", 50000))
    second_tab.cookies.set("lnr_customer_session", token)
    second_tab.cookies.set("lnr_customer_csrf", csrf)

    assert client.get("/api/v1/auth/me").status_code == 200
    assert second_tab.get("/api/v1/auth/me").status_code == 200
    assert client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": csrf},
    ).status_code == 200
    assert second_tab.get("/api/v1/auth/me").status_code == 401
    assert second_tab.get("/api/v1/bookings/me").status_code == 401
    assert second_tab.get("/api/v1/notifications").status_code == 401


def test_customer_profile_write_and_logout_still_require_csrf(client):
    assert register_customer(client).status_code == 201

    blocked = client.patch("/api/v1/auth/profile", json={"first_name": "New"})
    saved = client.patch(
        "/api/v1/auth/profile",
        json={"first_name": "New"},
        headers={"X-CSRF-Token": client.cookies.get("lnr_customer_csrf")},
    )
    logout = client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": client.cookies.get("lnr_customer_csrf")},
    )

    assert blocked.status_code == 403
    assert saved.status_code == 200
    assert logout.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_password_reset_tokens_are_one_time_and_never_returned(client, auth_test_db, monkeypatch):
    settings = get_settings()
    configure_reset_smtp(settings, monkeypatch)
    monkeypatch.setattr(auth_routes, "get_session_factory", lambda: auth_test_db)
    delivered = {}

    def fake_send(destination: str, raw_token: str):
        delivered["destination"] = destination
        delivered["token"] = raw_token

    monkeypatch.setattr(auth_routes, "_send_password_reset_email", fake_send)
    registered = register_customer(client)
    requested = request_password_reset(client, "customer@gmail.com")

    assert requested.status_code == 202
    assert "token" not in requested.text.lower()
    assert delivered["destination"] == "customer@gmail.com"
    with auth_test_db() as db:
        reset = db.scalar(select(CustomerPasswordResetToken))
        assert reset is not None
        assert reset.token_hash != delivered["token"]
    changed = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": delivered["token"],
            "password": "a-new-customer-password-123",
            "confirm_password": "a-new-customer-password-123",
        },
    )
    assert changed.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
    replay = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": delivered["token"],
            "password": "a-new-customer-password-123",
            "confirm_password": "a-new-customer-password-123",
        },
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "customer@gmail.com", "password": "a-new-customer-password-123"},
    )

    assert registered.status_code == 201
    assert replay.status_code == 400
    assert login.status_code == 200


def test_password_reset_expired_token_is_rejected(client, auth_test_db, monkeypatch):
    settings = get_settings()
    configure_reset_smtp(settings, monkeypatch)
    monkeypatch.setattr(auth_routes, "get_session_factory", lambda: auth_test_db)
    delivered = {}

    def fake_send(_destination: str, raw_token: str):
        delivered["token"] = raw_token

    monkeypatch.setattr(auth_routes, "_send_password_reset_email", fake_send)
    assert register_customer(client).status_code == 201
    assert request_password_reset(client, "customer@gmail.com").status_code == 202
    with auth_test_db() as db:
        reset = db.scalar(select(CustomerPasswordResetToken))
        assert reset is not None
        reset.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": delivered["token"],
            "password": "a-new-customer-password-123",
            "confirm_password": "a-new-customer-password-123",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Password reset link is invalid or expired."


def test_known_unknown_and_unconfigured_reset_requests_are_generic(
    client, auth_test_db, monkeypatch
):
    settings = get_settings()
    configure_reset_smtp(settings, monkeypatch)
    monkeypatch.setattr(auth_routes, "get_session_factory", lambda: auth_test_db)
    delivered = []
    monkeypatch.setattr(
        auth_routes,
        "_send_password_reset_email",
        lambda destination, _token: delivered.append(destination),
    )
    assert register_customer(client).status_code == 201

    known = request_password_reset(client, "customer@gmail.com")
    unknown = request_password_reset(client, "unknown@gmail.com")
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert delivered == ["customer@gmail.com"]

    monkeypatch.setattr(settings, "smtp_password", None)
    unconfigured = request_password_reset(client, "customer@gmail.com")
    assert unconfigured.status_code == 202
    assert unconfigured.json() == known.json()


def test_password_reset_smtp_failure_is_generic_and_revokes_undelivered_token(
    client, auth_test_db, monkeypatch, caplog
):
    settings = get_settings()
    configure_reset_smtp(settings, monkeypatch)
    monkeypatch.setattr(auth_routes, "get_session_factory", lambda: auth_test_db)
    registered = register_customer(client)

    def fail_send(destination: str, raw_token: str):
        error = (
            f"authentication failed for {destination}; "
            f"password={settings.smtp_password}; token={raw_token}"
        )
        raise smtplib.SMTPAuthenticationError(535, error.encode())

    monkeypatch.setattr(auth_routes, "_send_password_reset_email", fail_send)
    response = request_password_reset(client, "customer@gmail.com")
    unknown_response = request_password_reset(client, "unknown@gmail.com")

    assert response.status_code == 202
    assert response.json() == {"message": auth_routes.GENERIC_RESET_MESSAGE}
    assert unknown_response.status_code == response.status_code
    assert unknown_response.json() == response.json()
    assert "Password reset email delivery failed" in caplog.text
    assert "SMTPAuthenticationError" in caplog.text
    assert "SMTP server rejected authentication." in caplog.text
    assert settings.smtp_username not in caplog.text
    assert settings.smtp_password not in caplog.text
    assert "customer@gmail.com" not in caplog.text
    assert "authentication failed" not in caplog.text
    assert "token=" not in caplog.text
    with auth_test_db() as db:
        reset = db.scalar(select(CustomerPasswordResetToken))
        failure = db.scalar(
            select(AuthAuditLog).where(
                AuthAuditLog.action == "customer_password_reset_delivery_failed"
            )
        )
        assert reset is not None and reset.consumed_at is not None
        assert failure is not None
        assert failure.details == {
            "error_type": "SMTPAuthenticationError",
            "smtp_code": 535,
        }

    assert registered.status_code == 201


def test_password_reset_per_ip_limit_counts_failed_deliveries(
    client, auth_test_db, monkeypatch
):
    settings = get_settings()
    configure_reset_smtp(settings, monkeypatch)
    monkeypatch.setattr(settings, "password_reset_ip_limit", 2)
    monkeypatch.setattr(settings, "password_reset_email_limit", 10)
    monkeypatch.setattr(auth_routes, "get_session_factory", lambda: auth_test_db)
    calls = []

    def fail_send(destination: str, _raw_token: str):
        calls.append(destination)
        raise smtplib.SMTPException("test provider failure")

    monkeypatch.setattr(auth_routes, "_send_password_reset_email", fail_send)
    assert register_customer(client).status_code == 201

    responses = [request_password_reset(client, "customer@gmail.com") for _ in range(3)]

    assert all(response.status_code == 202 for response in responses)
    assert all(response.json() == responses[0].json() for response in responses)
    assert len(calls) == 2
    with auth_test_db() as db:
        request_count = db.scalar(
            select(func.count()).select_from(AuthAuditLog).where(
                AuthAuditLog.action == "customer_password_reset_requested"
            )
        )
        limited_count = db.scalar(
            select(func.count()).select_from(AuthAuditLog).where(
                AuthAuditLog.action == "customer_password_reset_rate_limited"
            )
        )
        assert request_count == 2
        assert limited_count == 1


def test_password_reset_per_email_limit_is_shared_across_ips(
    client, auth_test_db, monkeypatch
):
    settings = get_settings()
    configure_reset_smtp(settings, monkeypatch)
    monkeypatch.setattr(settings, "password_reset_ip_limit", 10)
    monkeypatch.setattr(settings, "password_reset_email_limit", 2)
    monkeypatch.setattr(auth_routes, "get_session_factory", lambda: auth_test_db)
    calls = []
    monkeypatch.setattr(
        auth_routes,
        "_send_password_reset_email",
        lambda destination, _token: calls.append(destination),
    )
    assert register_customer(client).status_code == 201

    responses = []
    for index in range(3):
        with TestClient(app, client=(f"127.0.0.{index + 2}", 50100 + index)) as remote_client:
            responses.append(request_password_reset(remote_client, "customer@gmail.com"))

    assert all(response.status_code == 202 for response in responses)
    assert all(response.json() == responses[0].json() for response in responses)
    assert calls == ["customer@gmail.com", "customer@gmail.com"]
    with auth_test_db() as db:
        attempts = list(
            db.scalars(
                select(AuthAuditLog).where(
                    AuthAuditLog.action == "customer_password_reset_requested"
                )
            )
        )
        assert len(attempts) == 2
        expected_email_hash = auth_routes._password_reset_email_hash("customer@gmail.com")
        assert all(row.details == {"email_hash": expected_email_hash} for row in attempts)


def test_brevo_smtp_transport_uses_separate_smtp_credentials(monkeypatch):
    settings = get_settings()
    configure_reset_smtp(settings, monkeypatch)
    observed = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            observed.update(host=host, port=port, timeout=timeout)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def starttls(self):
            observed["starttls"] = True

        def login(self, username, password):
            observed["login"] = (username, password)

        def send_message(self, message):
            observed["message"] = message

    monkeypatch.setattr(auth_routes.smtplib, "SMTP", FakeSMTP)
    auth_routes._send_password_reset_email("customer@example.test", "random-token")

    assert observed["host"] == "smtp.example.test"
    assert observed["port"] == 587
    assert observed["timeout"] == 30
    assert observed["starttls"] is True
    assert observed["login"] == ("smtp-user@example.test", "test-only-smtp-password")
    assert observed["message"]["To"] == "customer@example.test"


def test_password_reset_smtp_diagnostics_do_not_log_sensitive_values(
    client, auth_test_db, monkeypatch, caplog
):
    settings = get_settings()
    configure_reset_smtp(settings, monkeypatch)
    monkeypatch.setattr(settings, "smtp_username", "smtp-credential-secret")
    monkeypatch.setattr(settings, "smtp_password", "smtp-password-secret")
    monkeypatch.setattr(settings, "smtp_from_email", "sender-private@example.test")
    monkeypatch.setattr(auth_routes, "get_session_factory", lambda: auth_test_db)
    sent_messages = []

    class FakeSMTP:
        def __init__(self, _host, _port, timeout):
            assert timeout == 30

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def starttls(self):
            return None

        def login(self, _username, _password):
            return None

        def send_message(self, message):
            sent_messages.append(message)

    monkeypatch.setattr(auth_routes.smtplib, "SMTP", FakeSMTP)
    caplog.set_level("INFO", logger=auth_routes.__name__)
    assert register_customer(client).status_code == 201

    response = request_password_reset(client, "customer@gmail.com")

    assert response.status_code == 202
    assert len(sent_messages) == 1
    body = sent_messages[0].get_content()
    reset_token = body.split("token=", 1)[1].split()[0]
    assert "Password reset SMTP configuration complete: True" in caplog.text
    assert "Password reset email delivery background task started." in caplog.text
    assert "Password reset SMTP connection succeeded." in caplog.text
    assert "Password reset SMTP authentication succeeded." in caplog.text
    assert "Password reset email accepted by SMTP server." in caplog.text
    assert "smtp-credential-secret" not in caplog.text
    assert "smtp-password-secret" not in caplog.text
    assert "sender-private@example.test" not in caplog.text
    assert "customer@gmail.com" not in caplog.text
    assert reset_token not in caplog.text



def test_legacy_customer_can_establish_email_credentials_without_changing_user_id(client, auth_test_db):
    with auth_test_db() as db:
        user = User(mobile="+919876543210", status="active")
        db.add(user)
        db.flush()
        db.add(CustomerProfile(user_id=user.id, first_name="Legacy"))
        raw_token = "legacy-session-token"
        csrf = "legacy-csrf-token"
        db.add(
            AuthSession(
                user_id=user.id,
                token_hash=hash_token(raw_token),
                csrf_token_hash=hashlib.sha256(csrf.encode()).hexdigest(),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        db.commit()
        user_id = str(user.id)
    client.cookies.set("lnr_customer_session", raw_token)
    client.cookies.set("lnr_customer_csrf", csrf)
    response = client.post(
        "/api/v1/auth/credentials",
        json={
            "email": "legacy@example.net",
            "password": "a-legacy-account-password",
            "confirm_password": "a-legacy-account-password",
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    assert response.json()["id"] == user_id
    assert client.get("/api/v1/auth/me").json()["id"] == user_id


def create_admin(factory: sessionmaker[Session], *, role: str = "owner") -> tuple[AdminAccount, str]:
    secret = "JBSWY3DPEHPK3PXP"
    with factory() as db:
        admin = AdminAccount(
            username=f"operator-{role}",
            email=f"{role}@example.test",
            password_hash=password_hasher.hash("a-secure-local-test-password"),
            totp_secret_encrypted=encrypt_totp_secret(secret),
            role=role,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        return admin, secret


def totp_code(secret: str) -> str:
    key = base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8))
    counter = int(time.time() // 30).to_bytes(8, "big")
    digest = hmac.new(key, counter, hashlib.sha1).digest()
    offset = digest[-1] & 15
    number = (
        ((digest[offset] & 127) << 24)
        | ((digest[offset + 1] & 255) << 16)
        | ((digest[offset + 2] & 255) << 8)
        | (digest[offset + 3] & 255)
    )
    return f"{number % 1_000_000:06d}"


def test_legacy_otp_routes_are_removed_and_otp_table_model_is_retained(client, auth_test_db):
    assert client.post("/api/v1/auth/request-otp", json={"mobile": "9876543210"}).status_code == 404
    assert client.post("/api/v1/auth/resend-otp", json={"mobile": "9876543210"}).status_code == 404
    assert client.post(
        "/api/v1/auth/verify-otp",
        json={"mobile": "9876543210", "otp": "123456"},
    ).status_code == 404
    assert client.get("/api/v1/auth/dev/otp", params={"mobile": "9876543210"}).status_code == 404
    assert "otp_verification_records" in Base.metadata.tables


def test_customer_logout_requires_csrf_and_revokes_session(client):
    assert register_customer(client).status_code == 201

    csrf = client.cookies.get("lnr_customer_csrf")
    blocked = client.post("/api/v1/auth/logout")
    assert blocked.status_code == 403
    signed_out = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})

    assert signed_out.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_customer_profile_update_requires_csrf(client):
    assert register_customer(client).status_code == 201
    profile = {"first_name": "Ravi", "last_name": "Kumar"}

    blocked = client.patch("/api/v1/auth/profile", json=profile)
    csrf = client.cookies.get("lnr_customer_csrf")
    saved = client.patch(
        "/api/v1/auth/profile",
        json=profile,
        headers={"X-CSRF-Token": csrf},
    )

    assert blocked.status_code == 403
    assert saved.status_code == 200
    assert saved.json()["first_name"] == "Ravi"
    assert saved.json()["last_name"] == "Kumar"


def test_profile_update_ignores_client_supplied_customer_id(client, auth_test_db):
    registration = register_customer(client)
    assert registration.status_code == 201
    with auth_test_db() as db:
        other_customer = User(mobile="+919876543211", status="active")
        db.add(other_customer)
        db.flush()
        other_profile = CustomerProfile(
            user_id=other_customer.id,
            first_name="Other",
            last_name="Customer",
        )
        db.add(other_profile)
        db.commit()
        other_customer_id = other_customer.id

    updated = client.patch(
        "/api/v1/auth/profile",
        json={"user_id": str(other_customer_id), "first_name": "Authenticated"},
        headers={"X-CSRF-Token": client.cookies.get("lnr_customer_csrf")},
    )

    assert updated.status_code == 200
    assert updated.json()["id"] == registration.json()["id"]
    assert updated.json()["first_name"] == "Authenticated"
    with auth_test_db() as db:
        other_profile = db.scalar(
            select(CustomerProfile).where(
                CustomerProfile.user_id == other_customer_id
            )
        )
        assert other_profile is not None
        assert other_profile.first_name == "Other"
        own_profile = db.scalar(
            select(CustomerProfile).where(
                CustomerProfile.user_id == UUID(registration.json()["id"])
            )
        )
        assert own_profile is not None
        assert own_profile.first_name == "Authenticated"


def test_cross_origin_state_change_is_rejected(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Test Customer",
            "email": "customer@gmail.com",
            "mobile": "9876543210",
            "password": "a-customer-password-123",
            "confirm_password": "a-customer-password-123",
        },
        headers={"Origin": "https://attacker.example"},
    )

    assert response.status_code == 403


def test_expired_session_is_rejected(client, auth_test_db):
    assert register_customer(client).status_code == 201
    token = client.cookies.get("lnr_customer_session")
    with auth_test_db() as db:
        auth_session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
        assert auth_session is not None
        auth_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()
    assert client.get("/api/v1/bookings/me").status_code == 401
    assert client.get("/api/v1/notifications").status_code == 401


def test_blocked_and_revoked_customer_sessions_are_denied_everywhere(
    client, auth_test_db
):
    registration = register_customer(client)
    assert registration.status_code == 201
    token = client.cookies.get("lnr_customer_session")
    csrf = client.cookies.get("lnr_customer_csrf")
    with auth_test_db() as db:
        user = db.get(User, UUID(registration.json()["id"]))
        session = db.scalar(
            select(AuthSession).where(AuthSession.token_hash == hash_token(token))
        )
        assert user is not None and session is not None
        user.status = "blocked"
        db.commit()

    blocked_responses = (
        client.get("/api/v1/auth/me"),
        client.get("/api/v1/bookings/me"),
        client.get("/api/v1/notifications"),
    )
    assert [response.status_code for response in blocked_responses] == [403, 403, 403]

    with auth_test_db() as db:
        user = db.get(User, UUID(registration.json()["id"]))
        session = db.scalar(
            select(AuthSession).where(AuthSession.token_hash == hash_token(token))
        )
        assert user is not None and session is not None
        user.status = "active"
        session.revoked_at = datetime.now(UTC)
        db.commit()

    revoked_responses = (
        client.get("/api/v1/auth/me"),
        client.get("/api/v1/bookings/me"),
        client.get("/api/v1/notifications"),
        client.patch(
            "/api/v1/auth/profile",
            json={"first_name": "Should not save"},
            headers={"X-CSRF-Token": csrf},
        ),
    )
    assert [response.status_code for response in revoked_responses] == [401, 401, 401, 401]


def test_admin_login_requires_password_and_mfa(client, auth_test_db):
    admin, secret = create_admin(auth_test_db)
    wrong_password = client.post(
        "/api/v1/admin/auth/login",
        json={"username_or_email": admin.username, "password": "incorrect-password"},
    )
    assert wrong_password.status_code == 401
    assert client.get("/api/v1/admin/dashboard").status_code == 401

    login = client.post(
        "/api/v1/admin/auth/login",
        json={"username_or_email": admin.email, "password": "a-secure-local-test-password"},
    )
    assert login.status_code == 200
    assert login.json()["mfa_required"] is True
    csrf = client.cookies.get("lnr_admin_csrf")
    assert login.headers["x-csrf-token"] == csrf
    assert client.get("/api/v1/admin/dashboard").status_code == 401

    bad_mfa = client.post(
        "/api/v1/admin/auth/mfa/verify",
        json={"code": "000000"},
        headers={"X-CSRF-Token": csrf},
    )
    assert bad_mfa.status_code == 401
    verified = client.post(
        "/api/v1/admin/auth/mfa/verify",
        json={"code": totp_code(secret)},
        headers={"X-CSRF-Token": csrf},
    )

    assert verified.status_code == 200
    assert verified.json()["username"] == admin.username
    assert verified.headers["x-csrf-token"] == csrf
    current_admin = client.get("/api/v1/admin/auth/me")
    assert current_admin.status_code == 200
    assert current_admin.headers["x-csrf-token"] == csrf
    assert client.get("/api/v1/admin/dashboard").status_code == 200


def test_admin_login_is_blocked_while_mfa_reset_is_pending(client, auth_test_db):
    admin, _ = create_admin(auth_test_db)
    with auth_test_db() as db:
        account = db.get(AdminAccount, admin.id)
        assert account is not None
        account.mfa_configured = False
        db.commit()

    response = client.post(
        "/api/v1/admin/auth/login",
        json={"username_or_email": admin.username, "password": "a-secure-local-test-password"},
    )

    assert response.status_code == 403
    assert "local CLI" in response.json()["detail"]
    with auth_test_db() as db:
        assert db.scalar(
            select(AuthSession).where(AuthSession.admin_id == admin.id)
        ) is None


def test_local_development_password_only_login_allows_pending_mfa(
    client, auth_test_db, monkeypatch
):
    admin, _ = create_admin(auth_test_db)
    with auth_test_db() as db:
        account = db.get(AdminAccount, admin.id)
        assert account is not None
        account.mfa_configured = False
        db.commit()
    monkeypatch.setattr(get_settings(), "admin_mfa_required", False)

    response = client.post(
        "/api/v1/admin/auth/login",
        json={"username_or_email": admin.username, "password": "a-secure-local-test-password"},
    )

    assert response.status_code == 200
    assert response.json()["mfa_required"] is False
    assert "lnr_admin_session" in response.cookies
    assert client.get("/api/v1/admin/auth/me").status_code == 200
    assert client.get("/api/v1/admin/dashboard").status_code == 200
    with auth_test_db() as db:
        session = db.scalar(
            select(AuthSession).where(AuthSession.admin_id == admin.id)
        )
        assert session is not None
        assert session.is_mfa_verified is True
        expires_at = session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        assert expires_at > datetime.now(UTC) + timedelta(minutes=5)


def test_password_only_is_denied_from_non_local_development_client(
    auth_test_db, monkeypatch
):
    admin, _ = create_admin(auth_test_db)
    monkeypatch.setattr(get_settings(), "admin_mfa_required", False)

    with TestClient(app, client=("192.0.2.10", 50000)) as remote_client:
        response = remote_client.post(
            "/api/v1/admin/auth/login",
            json={"username_or_email": admin.username, "password": "a-secure-local-test-password"},
        )

    assert response.status_code == 200
    assert response.json()["mfa_required"] is True
    assert "lnr_admin_session" in response.cookies
    with auth_test_db() as db:
        session = db.scalar(select(AuthSession).where(AuthSession.admin_id == admin.id))
        assert session is not None
        assert session.is_mfa_verified is False


def test_production_always_requires_mfa_even_if_setting_is_false(
    client, auth_test_db, monkeypatch
):
    admin, _ = create_admin(auth_test_db)
    monkeypatch.setattr(get_settings(), "app_env", "production")
    monkeypatch.setattr(get_settings(), "admin_mfa_required", False)

    response = client.post(
        "/api/v1/admin/auth/login",
        json={"username_or_email": admin.email, "password": "a-secure-local-test-password"},
    )

    assert response.status_code == 200
    assert response.json()["mfa_required"] is True
    assert "lnr_admin_session" in response.cookies
    with auth_test_db() as db:
        session = db.scalar(select(AuthSession).where(AuthSession.admin_id == admin.id))
        assert session is not None
        assert session.is_mfa_verified is False


def test_admin_session_cookies_support_cross_site_requests_in_production(
    client, auth_test_db, monkeypatch
):
    admin, _ = create_admin(auth_test_db)
    monkeypatch.setattr(get_settings(), "app_env", "production")
    monkeypatch.setattr(get_settings(), "secure_cookies", False)

    response = client.post(
        "/api/v1/admin/auth/login",
        json={"username_or_email": admin.username, "password": "a-secure-local-test-password"},
    )

    assert response.status_code == 200
    cookie_headers = response.headers.get_list("set-cookie")
    session_cookie = next(header for header in cookie_headers if header.startswith("lnr_admin_session="))
    csrf_cookie = next(header for header in cookie_headers if header.startswith("lnr_admin_csrf="))
    assert "secure" in session_cookie.lower()
    assert "httponly" in session_cookie.lower()
    assert "samesite=none" in session_cookie.lower()
    assert "secure" in csrf_cookie.lower()
    assert "httponly" not in csrf_cookie.lower()
    assert "samesite=none" in csrf_cookie.lower()


def test_customer_cannot_access_admin_endpoints(client):
    assert register_customer(client).status_code == 201

    dashboard = client.get("/api/v1/admin/dashboard")
    current_admin = client.get("/api/v1/admin/auth/me")
    admin_logout = client.post("/api/v1/admin/auth/logout")

    assert dashboard.status_code == 401
    assert current_admin.status_code == 401
    assert admin_logout.status_code == 401


def test_admin_and_customer_sessions_are_not_interchangeable(
    client, auth_test_db
):
    registration = register_customer(client)
    admin, secret = create_admin(auth_test_db)
    password_login = client.post(
        "/api/v1/admin/auth/login",
        json={
            "username_or_email": admin.username,
            "password": "a-secure-local-test-password",
        },
    )
    assert password_login.status_code == 200
    admin_csrf = client.cookies.get("lnr_admin_csrf")
    verified = client.post(
        "/api/v1/admin/auth/mfa/verify",
        json={"code": totp_code(secret)},
        headers={"X-CSRF-Token": admin_csrf},
    )
    assert verified.status_code == 200

    customer_only = TestClient(app, client=("127.0.0.1", 50000))
    customer_only.cookies.set(
        "lnr_customer_session", registration.cookies.get("lnr_customer_session")
    )
    admin_only = TestClient(app, client=("127.0.0.1", 50000))
    admin_only.cookies.set("lnr_admin_session", client.cookies.get("lnr_admin_session"))

    assert customer_only.get("/api/v1/auth/me").status_code == 200
    assert customer_only.get("/api/v1/admin/auth/me").status_code == 401
    assert admin_only.get("/api/v1/admin/auth/me").status_code == 200
    assert admin_only.get("/api/v1/auth/me").status_code == 401


def test_cors_allows_configured_frontend_with_credentials(client):
    response = client.options(
        "/api/v1/auth/me",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-csrf-token",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_admin_role_is_enforced(client, auth_test_db):
    admin, secret = create_admin(auth_test_db, role="support")
    client.post(
        "/api/v1/admin/auth/login",
        json={"username_or_email": admin.username, "password": "a-secure-local-test-password"},
    )
    csrf = client.cookies.get("lnr_admin_csrf")
    mfa = client.post(
        "/api/v1/admin/auth/mfa/verify",
        json={"code": totp_code(secret)},
        headers={"X-CSRF-Token": csrf},
    )
    assert mfa.status_code == 200

    response = client.get("/api/v1/admin/dashboard")

    assert response.status_code == 403
    with auth_test_db() as db:
        assert db.scalar(
            select(AuthAuditLog).where(AuthAuditLog.action == "admin_login")
        ) is not None
