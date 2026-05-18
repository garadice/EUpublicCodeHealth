"""API key authentication for protected endpoints.

If API_KEY is not set (empty), authentication is disabled for local development.
When set, all endpoints except /health require an X-API-Key header matching the key.
"""

import secrets

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import Settings, get_settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

SETTINGS_DEP = Depends(get_settings)
API_KEY_DEP = Security(api_key_header)


async def verify_api_key(
    settings: Settings = SETTINGS_DEP,
    api_key: str | None = API_KEY_DEP,
) -> None:
    """Verify the API key if authentication is enabled.

    Auth is enabled when API_KEY env var is set to a non-empty string.
    When disabled (empty/unset), all requests pass through.
    """
    # Auth disabled — no key configured
    if not settings.api_key:
        return

    # Auth enabled but no key provided
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    # Constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(api_key, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )


# Reusable dependency instance
require_api_key = Depends(verify_api_key)
