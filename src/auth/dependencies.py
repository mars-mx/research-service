"""API key validation (FastAPI dependency)."""

import hmac

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from src.config import Settings, get_settings

_api_key_header = APIKeyHeader(name="X-API-Key")


async def require_api_key(
    api_key: str = Security(_api_key_header),
    settings: Settings = Depends(get_settings),
) -> str:
    """Validate the X-API-Key header against the configured API_KEY."""
    if not hmac.compare_digest(api_key, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return api_key
