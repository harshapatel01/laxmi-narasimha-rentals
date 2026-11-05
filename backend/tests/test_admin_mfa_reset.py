import base64
import hashlib
import hmac
import io
import time
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import cli
from app.models.auth import AdminAccount, AuthAuditLog, AuthSession
from app.models.base import Base
from app.services.security import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    password_hasher,
    verify_totp,
)

TEST_PASSWORD = "a-secure-local-test-password"
OLD_SECRET = "JBSWY3DPEHPK3PXP"
NEW_SECRET = "MZXW6YTBOI"


@pytest.fixture
def admin_reset_db(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    admin_id = uuid4()
    with factory() as db:
        db.add(
            AdminAccount(
                id=admin_id,
                username="reset-operator",
                email="reset-operator@example.test",
                password_hash=password_hasher.hash(TEST_PASSWORD),
                totp_secret_encrypted=encrypt_totp_secret(OLD_SECRET),
                mfa_configured=True,
                role="owner",
            )
        )
        db.add(
            AuthSession(
                admin_id=admin_id,
                token_hash=f"{uuid4().hex}{uuid4().hex}",
                csrf_token_hash=f"{uuid4().hex}{uuid4().hex}",
                is_mfa_verified=True,
                expires_at=cli.datetime.now(cli.UTC),
            )
        )
        db.commit()
    monkeypatch.setattr(cli, "get_session_factory", lambda: factory)
    monkeypatch.setattr(cli, "generate_totp_secret", lambda: NEW_SECRET)
    yield factory, admin_id
    engine.dispose()


def current_totp(secret: str) -> str:
    normalized = secret + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(normalized)
    counter = int(time.time() // 30).to_bytes(8, "big")
    digest = hmac.new(key, counter, hashlib.sha1).digest()
    offset = digest[-1] & 15
    value = (
        ((digest[offset] & 127) << 24)
        | ((digest[offset + 1] & 255) << 16)
        | ((digest[offset + 2] & 255) << 8)
        | (digest[offset + 3] & 255)
    )
    return f"{value % 1_000_000:06d}"


def reset_with_new_code(factory: sessionmaker[Session], admin_id, *, display_uri):
    def prompt_code() -> str:
        with factory() as db:
            admin = db.get(AdminAccount, admin_id)
            assert admin is not None
            secret = decrypt_totp_secret(admin.totp_secret_encrypted)
        return current_totp(secret)

    return cli.reset_admin_mfa(
        "reset-operator",
        TEST_PASSWORD,
        prompt_code,
        display_uri,
    )


def test_reset_admin_mfa_reprovisions_and_requires_new_code(admin_reset_db):
    factory, admin_id = admin_reset_db
    displayed = []

    result = reset_with_new_code(
        factory,
        admin_id,
        display_uri=lambda uri: displayed.append(bool(uri)),
    )

    assert result == 0
    assert displayed == [True]
    with factory() as db:
        admin = db.get(AdminAccount, admin_id)
        assert admin is not None
        assert admin.mfa_configured is True
        new_secret = decrypt_totp_secret(admin.totp_secret_encrypted)
        assert new_secret == NEW_SECRET
        assert new_secret != OLD_SECRET
        assert db.scalar(
            select(AuthSession).where(
                AuthSession.admin_id == admin_id,
                AuthSession.revoked_at.is_(None),
            )
        ) is None
        assert db.scalar(
            select(AuthAuditLog).where(
                AuthAuditLog.admin_id == admin_id,
                AuthAuditLog.action == "admin_mfa_reset_completed",
            )
        ) is not None
    new_code = current_totp(NEW_SECRET)
    assert verify_totp(NEW_SECRET, new_code)
    assert not verify_totp(OLD_SECRET, new_code)


def test_reset_admin_mfa_rejects_incorrect_password_without_changing_secret(
    admin_reset_db,
):
    factory, admin_id = admin_reset_db
    displayed = []

    result = cli.reset_admin_mfa(
        "reset-operator",
        "incorrect-password",
        lambda: "000000",
        displayed.append,
    )

    assert result == 1
    assert displayed == []
    with factory() as db:
        admin = db.get(AdminAccount, admin_id)
        assert admin is not None
        assert admin.mfa_configured is True
        assert decrypt_totp_secret(admin.totp_secret_encrypted) == OLD_SECRET


def test_reset_admin_mfa_keeps_setup_pending_for_invalid_code(admin_reset_db):
    factory, admin_id = admin_reset_db
    with factory() as db:
        old_secret = decrypt_totp_secret(db.get(AdminAccount, admin_id).totp_secret_encrypted)
    invalid_code = next(
        f"{candidate:06d}"
        for candidate in range(1_000_000)
        if not verify_totp(NEW_SECRET, f"{candidate:06d}")
    )
    displayed = []

    result = cli.reset_admin_mfa(
        "reset-operator",
        TEST_PASSWORD,
        lambda: invalid_code,
        lambda uri: displayed.append(bool(uri)),
    )

    assert result == 1
    assert displayed == [True]
    with factory() as db:
        admin = db.get(AdminAccount, admin_id)
        assert admin is not None
        assert admin.mfa_configured is False
        assert decrypt_totp_secret(admin.totp_secret_encrypted) == NEW_SECRET
        assert decrypt_totp_secret(admin.totp_secret_encrypted) != old_secret
        assert db.scalar(
            select(AuthAuditLog).where(
                AuthAuditLog.admin_id == admin_id,
                AuthAuditLog.action == "admin_mfa_reset_verification_failed",
            )
        ) is not None


def test_reset_admin_mfa_cli_requires_an_interactive_terminal(monkeypatch, capsys):
    class NonInteractiveStream(io.StringIO):
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr(cli.sys, "argv", ["app.cli", "reset-admin-mfa"])
    monkeypatch.setattr(cli.sys, "stdin", NonInteractiveStream())
    monkeypatch.setattr(cli.sys, "stdout", NonInteractiveStream())

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 2
    captured = capsys.readouterr()
    assert "local interactive terminal" in captured.err
