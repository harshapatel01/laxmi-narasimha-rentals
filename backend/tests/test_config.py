from app.core.config import Settings


def test_database_url_encodes_reserved_password_characters() -> None:
    settings = Settings(db_password="p@ss:/?#")

    assert settings.database_url is not None
    connection_string = settings.database_url.render_as_string(hide_password=False)
    assert "p%40ss%3A%2F%3F%23" in connection_string
    assert "laxmi_narasimha_rentals" in connection_string


def test_secure_cookies_cannot_be_disabled_in_production() -> None:
    settings = Settings(app_env="production", secure_cookies=False)

    assert settings.cookies_are_secure is True


def test_secure_cookies_are_enabled_by_default_in_nonlocal_environments() -> None:
    settings = Settings(app_env="staging", secure_cookies=False)

    assert settings.cookies_are_secure is True


def test_secure_cookies_default_to_http_compatible_only_for_local_development() -> None:
    assert Settings(app_env="development").cookies_are_secure is False
    assert Settings(app_env="test").cookies_are_secure is False


def test_secure_cookies_can_be_enabled_for_nonproduction_https() -> None:
    settings = Settings(app_env="development", secure_cookies=True)

    assert settings.cookies_are_secure is True
