from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import settings

# Define the header scheme
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_api_key(api_key_header: str = Security(api_key_header)):
    """
    Validates the API Key provided in the header.
    If CHASSIS_API_KEY is set in environment, it enforces validation.
    If not set, it allows open access (for dev/testing).
    """
    # We need to add this to settings first, but for now accessing os.environ or
    # checking if we want to enforce it.
    # Let's assume we want to support an optional CHASSIS_API_KEY in settings.

    expected_key = getattr(settings, "CHASSIS_API_KEY", None)

    if expected_key:
        if api_key_header == expected_key:
            return api_key_header
        else:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Could not validate credentials")

    # If no key is configured on the server, we allow access
    return None
