from typing import Protocol


class SmsDeliveryError(Exception):
    pass


class SmsProvider(Protocol):
    def send_otp(self, mobile: str, otp: str) -> None: ...


class MockSmsProvider:
    def __init__(self) -> None:
        self._latest_otp: dict[str, str] = {}

    def send_otp(self, mobile: str, otp: str) -> None:
        self._latest_otp[mobile] = otp

    def get_latest_otp(self, mobile: str) -> str | None:
        return self._latest_otp.get(mobile)
