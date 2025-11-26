"""
Authentication API endpoints.

Provides user registration, login, email verification, Google OAuth,
and password reset functionality.

Part of OSP-14 implementation.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import settings
from app.schemas.auth import (
    GoogleAuthRequest,
    LoginRequest,
    PasswordResetConfirmRequest,
    PasswordResetConfirmResponse,
    PasswordResetRequest,
    PasswordResetResponse,
    RefreshTokenRequest,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    ResendVerificationResponse,
    TokenResponse,
    UserInfo,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from app.services.auth_service import auth_service

router = APIRouter()


def require_user_auth_enabled():
    """Dependency to check if user auth is enabled."""
    if not settings.ENABLE_USER_AUTH:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="User authentication is not enabled. Set ENABLE_USER_AUTH=true to enable.",
        )


# =============================================================================
# Registration
# =============================================================================


@router.post(
    "/register",
    response_model=RegisterResponse,
    dependencies=[Depends(require_user_auth_enabled)],
)
async def register(request: RegisterRequest) -> RegisterResponse:
    """
    Register a new user account.

    After registration, a verification email will be sent to the provided address.
    The user must verify their email before they can log in.

    **Request Body:**
    ```json
    {
        "email": "user@example.com",
        "password": "SecurePass123",
        "display_name": "John Doe"
    }
    ```

    **Password Requirements:**
    - Minimum 8 characters
    - At least one letter
    - At least one digit
    """
    user = await auth_service.register(
        email=request.email,
        password=request.password,
        display_name=request.display_name,
    )

    return RegisterResponse(
        user_id=user.id,
        email=user.email,
    )


# =============================================================================
# Email Verification
# =============================================================================


@router.post(
    "/verify-email",
    response_model=VerifyEmailResponse,
    dependencies=[Depends(require_user_auth_enabled)],
)
async def verify_email(request: VerifyEmailRequest) -> VerifyEmailResponse:
    """
    Verify email address with a 6-digit code.

    The code is sent to the user's email after registration.
    Codes expire after 15 minutes and allow maximum 3 attempts.

    **Request Body:**
    ```json
    {
        "email": "user@example.com",
        "code": "123456"
    }
    ```
    """
    await auth_service.verify_email(email=request.email, code=request.code)
    return VerifyEmailResponse()


@router.post(
    "/resend-verification",
    response_model=ResendVerificationResponse,
    dependencies=[Depends(require_user_auth_enabled)],
)
async def resend_verification(
    request: ResendVerificationRequest,
) -> ResendVerificationResponse:
    """
    Resend verification email.

    Rate limited to 1 email per minute.

    **Request Body:**
    ```json
    {
        "email": "user@example.com"
    }
    ```
    """
    await auth_service.resend_verification(email=request.email)
    return ResendVerificationResponse()


# =============================================================================
# Login
# =============================================================================


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(require_user_auth_enabled)],
)
async def login(request: LoginRequest) -> TokenResponse:
    """
    Login with email and password.

    Returns access and refresh tokens on successful authentication.
    The access token should be included in the Authorization header for subsequent requests.

    **Request Body:**
    ```json
    {
        "email": "user@example.com",
        "password": "SecurePass123"
    }
    ```

    **Response:**
    ```json
    {
        "access_token": "eyJ...",
        "refresh_token": "eyJ...",
        "token_type": "bearer",
        "expires_in": 1800
    }
    ```

    **Using the token:**
    ```
    Authorization: Bearer eyJ...
    ```
    """
    return await auth_service.login(email=request.email, password=request.password)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(require_user_auth_enabled)],
)
async def refresh_token(request: RefreshTokenRequest) -> TokenResponse:
    """
    Refresh an access token.

    Use this endpoint when your access token is about to expire or has expired.
    Provide the refresh token to get a new access token.

    **Request Body:**
    ```json
    {
        "refresh_token": "eyJ..."
    }
    ```
    """
    return await auth_service.refresh_token(refresh_token=request.refresh_token)


# =============================================================================
# Google OAuth
# =============================================================================


@router.post(
    "/google",
    response_model=TokenResponse,
    dependencies=[Depends(require_user_auth_enabled)],
)
async def google_auth(request: GoogleAuthRequest) -> TokenResponse:
    """
    Authenticate or register via Google OAuth.

    This endpoint accepts a Google ID token obtained from client-side Google Sign-In.
    If the user doesn't exist, a new account will be created automatically.
    If the user exists (by email), their Google account will be linked.

    **Request Body:**
    ```json
    {
        "id_token": "eyJ..."
    }
    ```

    **Client-side setup:**
    1. Include Google Sign-In SDK
    2. Configure with your GOOGLE_CLIENT_ID
    3. After sign-in, send the ID token to this endpoint

    **Response:**
    Same as `/login` - returns access and refresh tokens.
    """
    return await auth_service.google_auth(id_token=request.id_token)


# =============================================================================
# Password Reset
# =============================================================================


@router.post(
    "/password-reset",
    response_model=PasswordResetResponse,
    dependencies=[Depends(require_user_auth_enabled)],
)
async def request_password_reset(
    request: PasswordResetRequest,
) -> PasswordResetResponse:
    """
    Request a password reset.

    If an account exists with the provided email, a reset code will be sent.
    For security, the response is always the same whether or not the email exists.

    **Request Body:**
    ```json
    {
        "email": "user@example.com"
    }
    ```
    """
    await auth_service.request_password_reset(email=request.email)
    return PasswordResetResponse()


@router.post(
    "/password-reset/confirm",
    response_model=PasswordResetConfirmResponse,
    dependencies=[Depends(require_user_auth_enabled)],
)
async def confirm_password_reset(
    request: PasswordResetConfirmRequest,
) -> PasswordResetConfirmResponse:
    """
    Confirm password reset with code and new password.

    **Request Body:**
    ```json
    {
        "email": "user@example.com",
        "code": "123456",
        "new_password": "NewSecurePass123"
    }
    ```
    """
    await auth_service.confirm_password_reset(
        email=request.email,
        code=request.code,
        new_password=request.new_password,
    )
    return PasswordResetConfirmResponse()


# =============================================================================
# Current User
# =============================================================================


@router.get(
    "/me",
    response_model=UserInfo,
    dependencies=[Depends(require_user_auth_enabled)],
)
async def get_current_user_info(
    authorization: str | None = None,
) -> UserInfo:
    """
    Get information about the currently authenticated user.

    Requires a valid access token in the Authorization header.

    **Headers:**
    ```
    Authorization: Bearer eyJ...
    ```
    """
    from app.services.jwt_service import jwt_service

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    token = authorization.split(" ", 1)[1]
    payload = jwt_service.verify_access_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
        )

    user_id = payload.get("sub")
    user = await auth_service.get_user_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return UserInfo(
        id=user.id,
        email=user.email,
        email_verified=user.email_verified,
        has_google_auth=user.google_id is not None,
        display_name=user.display_name,
        created_at=user.created_at.isoformat() if user.created_at else "",
        is_admin=user.is_admin,
    )
