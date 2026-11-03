from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


def normalize_indian_mobile(value: str) -> str:
    compact = "".join(character for character in value if character not in " -()")
    if compact.startswith("0"):
        compact = compact[1:]
    if compact.startswith("+91"):
        national_number = compact[3:]
    elif compact.startswith("91") and len(compact) == 12:
        national_number = compact[2:]
    else:
        national_number = compact
    if len(national_number) != 10 or national_number[0] not in "6789" or not national_number.isdigit():
        raise ValueError("Enter a valid Indian mobile number.")
    return f"+91{national_number}"


class MessageResponse(BaseModel):
    message: str


class CustomerResponse(BaseModel):
    id: str
    mobile: str
    email: EmailStr | None = None
    mobile_verified: bool = False
    status: str
    first_name: str | None
    last_name: str | None


class CustomerProfileUpdate(BaseModel):
    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)


class CustomerRegistrationRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=160)
    email: EmailStr
    mobile: str = Field(min_length=10, max_length=18)
    password: str = Field(min_length=12, max_length=256)
    confirm_password: str = Field(min_length=12, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, value: str) -> str:
        return normalize_indian_mobile(value)

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Enter your full name.")
        return normalized

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        return self


class CustomerLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class CustomerCredentialSetupRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=160)
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    confirm_password: str = Field(min_length=12, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        return self


class PasswordResetRequest(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    password: str = Field(min_length=12, max_length=256)
    confirm_password: str = Field(min_length=12, max_length=256)

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        return self


class AdminLoginRequest(BaseModel):
    username_or_email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class AdminLoginResponse(BaseModel):
    mfa_required: bool


class MfaVerificationRequest(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class AdminResponse(BaseModel):
    id: str
    username: str
    email: str
    role: str

    model_config = ConfigDict(from_attributes=True)


class AdminCustomerResponse(BaseModel):
    id: str
    full_name: str | None
    email: EmailStr | None
    mobile: str
    status: str
    created_at: datetime


class AdminCustomerStatusChange(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        normalized = value.strip() if value is not None else None
        return normalized or None


class AdminSensitiveActionRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        normalized = value.strip() if value is not None else None
        return normalized or None
