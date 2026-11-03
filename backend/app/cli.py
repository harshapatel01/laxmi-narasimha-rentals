import argparse
import getpass
import hmac
import sys
from collections.abc import Callable
from datetime import UTC, datetime

from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import get_session_factory
from app.models.auth import AdminAccount, AuthAuditLog, AuthSession
from app.services.security import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_totp_secret,
    password_hasher,
    provisioning_uri,
    verify_totp,
)
from app.services.whatsapp_cloud import send_whatsapp_connectivity_test


def bootstrap_admin() -> int:
    username = input("Admin username: ").strip().lower()
    email = input("Admin email: ").strip().lower()
    password = getpass.getpass("Admin password (12+ characters): ")
    confirmation = getpass.getpass("Confirm admin password: ")
    if not username or not email or len(password) < 12:
        print("Username/email are required and the password must be at least 12 characters.", file=sys.stderr)
        return 2
    if password != confirmation:
        print("Passwords do not match.", file=sys.stderr)
        return 2

    totp_secret = generate_totp_secret()
    factory = get_session_factory()
    with factory() as db:
        if db.scalar(select(AdminAccount.id).limit(1)) is not None:
            print("An administrator already exists; bootstrap is only for the first admin.", file=sys.stderr)
            return 1
        account = AdminAccount(
            username=username,
            email=email,
            password_hash=password_hasher.hash(password),
            totp_secret_encrypted=encrypt_totp_secret(totp_secret),
            role="owner",
        )
        db.add(account)
        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            print("Unable to create the administrator; verify the username/email are unique.", file=sys.stderr)
            raise

    print("Administrator created. Add this one-time provisioning URI to an authenticator app:")
    print(provisioning_uri(totp_secret, username))
    print("Do not share or save the URI in source control.")
    return 0


def reset_admin_mfa(
    identity: str,
    password: str,
    prompt_code: Callable[[], str],
    display_uri: Callable[[str], None],
) -> int:
    factory = get_session_factory()
    with factory() as db:
        admin = db.scalar(
            select(AdminAccount)
            .where(
                or_(
                    AdminAccount.username == identity.lower(),
                    AdminAccount.email == identity.lower(),
                )
            )
            .with_for_update()
        )
        try:
            password_matches = admin is not None and password_hasher.verify(
                admin.password_hash, password
            )
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            password_matches = False

        if not password_matches or admin is None or admin.status != "active":
            db.add(
                AuthAuditLog(
                    admin_id=admin.id if admin else None,
                    action="admin_mfa_reset_failed",
                )
            )
            db.commit()
            print("Unable to authorize MFA reset.", file=sys.stderr)
            return 1

        new_secret = generate_totp_secret()
        encrypted_secret = encrypt_totp_secret(new_secret)
        admin.totp_secret_encrypted = encrypted_secret
        admin.mfa_configured = False
        active_sessions = db.scalars(
            select(AuthSession)
            .where(
                AuthSession.admin_id == admin.id,
                AuthSession.revoked_at.is_(None),
            )
            .with_for_update()
        )
        for session in active_sessions:
            session.revoked_at = datetime.now(UTC)
        db.add(
            AuthAuditLog(
                admin_id=admin.id,
                action="admin_mfa_reset_started",
            )
        )
        db.commit()
        admin_username = admin.username
        admin_id = admin.id

    display_uri(provisioning_uri(new_secret, admin_username))
    print("Enter a current code from the newly configured authenticator to finish setup.")
    for _ in range(5):
        code = prompt_code().strip()
        if len(code) != 6 or not code.isdigit() or not verify_totp(new_secret, code):
            with factory() as db:
                db.add(
                    AuthAuditLog(
                        admin_id=admin_id,
                        action="admin_mfa_reset_verification_failed",
                    )
                )
                db.commit()
            print("That code was not accepted. The new MFA setup is still pending.", file=sys.stderr)
            continue

        with factory() as db:
            current_admin = db.scalar(
                select(AdminAccount)
                .where(AdminAccount.id == admin_id)
                .with_for_update()
            )
            if (
                current_admin is None
                or not hmac.compare_digest(
                    current_admin.totp_secret_encrypted, encrypted_secret
                )
            ):
                print("MFA setup changed concurrently; run the reset command again.", file=sys.stderr)
                return 1
            current_admin.mfa_configured = True
            db.add(
                AuthAuditLog(
                    admin_id=admin_id,
                    action="admin_mfa_reset_completed",
                )
            )
            try:
                db.commit()
            except SQLAlchemyError:
                db.rollback()
                print("Unable to complete MFA setup; run the reset command again.", file=sys.stderr)
                raise
        print("Administrator MFA reset and verified.")
        return 0

    print("MFA setup remains pending. Run the reset command again to start over.", file=sys.stderr)
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Laxmi Narasimha Rentals backend administration")
    parser.add_argument(
        "command",
        choices=["bootstrap-admin", "reset-admin-mfa", "test-whatsapp"],
    )
    args = parser.parse_args()
    if args.command == "bootstrap-admin":
        raise SystemExit(bootstrap_admin())
    if args.command == "reset-admin-mfa":
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            print("MFA reset must be run in a local interactive terminal.", file=sys.stderr)
            raise SystemExit(2)
        identity = input("Admin username or email: ").strip().lower()
        password = getpass.getpass("Current admin password: ")
        if not identity or not password:
            print("An administrator identity and password are required.", file=sys.stderr)
            raise SystemExit(2)
        result = reset_admin_mfa(
            identity,
            password,
            lambda: getpass.getpass("New authenticator code: "),
            print,
        )
        raise SystemExit(result)
    if args.command == "test-whatsapp":
        result = send_whatsapp_connectivity_test()
        if result.accepted:
            print("Meta accepted the generic hello_world connectivity test.")
            raise SystemExit(0)
        print(
            f"WhatsApp connectivity test was not accepted ({result.reason}).",
            file=sys.stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
