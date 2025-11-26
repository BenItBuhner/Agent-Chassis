"""
Pydantic schemas for authentication API requests and responses.

Part of OSP-14 implementation - User account creation and authentication.
"""

from pydantic import BaseModel, EmailStr, Field, field_validator

# =============================================================================
# Registration
# =============================================================================


class RegisterRequest(BaseModel):
    """Request to register a new user account with email and password."""

    email: EmailStr
    password: str = Field(..., min_length=8, description="Password (minimum 8 characters)")
    display_name: str | None = Field(None, max_length=255, description="Display name")

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Ensure password has basic strength requirements."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        if not any(c.isalpha() for c in v):
            raise ValueError("Password must contain at least one letter")
        return v


class RegisterResponse(BaseModel):
    """Response after successful registration."""

    user_id: str
    email: str
    message: str = "Verification email sent. Please check your inbox."


# =============================================================================
# Email Verification
# =============================================================================


class VerifyEmailRequest(BaseModel):
    """Request to verify email address with a code."""

    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6, description="6-digit verification code")


class VerifyEmailResponse(BaseModel):
    """Response after successful email verification."""

    success: bool = True
    message: str = "Email verified successfully. You can now log in."


class ResendVerificationRequest(BaseModel):
    """Request to resend verification email."""

    email: EmailStr


class ResendVerificationResponse(BaseModel):
    """Response after resending verification email."""

    success: bool = True
    message: str = "Verification email sent. Please check your inbox."


# =============================================================================
# Login
# =============================================================================


class LoginRequest(BaseModel):
    """Request to login with email and password."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Response containing authentication tokens."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Access token expiry in seconds")


class RefreshTokenRequest(BaseModel):
    """Request to refresh an access token."""

    refresh_token: str


# =============================================================================
# Google OAuth
# =============================================================================


class GoogleAuthRequest(BaseModel):
    """Request to authenticate via Google OAuth."""

    id_token: str = Field(..., description="Google ID token from client-side sign-in")


# =============================================================================
# Password Reset
# =============================================================================


class PasswordResetRequest(BaseModel):
    """Request to initiate password reset."""

    email: EmailStr


class PasswordResetResponse(BaseModel):
    """Response after requesting password reset."""

    success: bool = True
    message: str = "If an account exists with this email, a reset code has been sent."


class PasswordResetConfirmRequest(BaseModel):
    """Request to confirm password reset with code and new password."""

    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6, description="6-digit reset code")
    new_password: str = Field(..., min_length=8, description="New password (minimum 8 characters)")

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Ensure password has basic strength requirements."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        if not any(c.isalpha() for c in v):
            raise ValueError("Password must contain at least one letter")
        return v


class PasswordResetConfirmResponse(BaseModel):
    """Response after successful password reset."""

    success: bool = True
    message: str = "Password reset successful. You can now log in with your new password."


# =============================================================================
# User Info
# =============================================================================


class UserInfo(BaseModel):
    """Current user information (returned by /auth/me)."""

    id: str
    email: str
    email_verified: bool
    has_google_auth: bool = Field(..., description="Whether Google OAuth is linked")
    display_name: str | None
    created_at: str
    is_admin: bool = False


class MessageResponse(BaseModel):
    """Generic message response."""

    success: bool = True
    message: str
