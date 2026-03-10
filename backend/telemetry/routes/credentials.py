"""Routes for managing stored provider credentials."""

from __future__ import annotations

from typing import AsyncIterator, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import NoResultFound

from ..db import get_session
from ..models import StoredCredential, User
from ..repository import TelemetryRepository
from ..routes.auth import get_current_user
from ..schemas import (
    CredentialCreate,
    CredentialDetail,
    CredentialUpdate,
    CredentialWithSecret,
)

router = APIRouter(prefix="/credentials", tags=["Credentials"])


def _preview_secret(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}…{secret[-4:]}"


def _to_detail(credential: StoredCredential, *, secret: Optional[str] = None) -> CredentialDetail:
    preview = _preview_secret(secret) if secret else None
    return CredentialDetail(
        credential_id=credential.credential_id,
        provider=credential.provider,
        name=credential.name,
        credential_type=credential.credential_type,
        description=credential.description,
        metadata=credential.metadata_json,
        created_at=credential.created_at,
        updated_at=credential.updated_at,
        last_used_at=credential.last_used_at,
        secret_available=bool(credential.secret_ciphertext),
        secret_preview=preview,
    )


async def get_repository() -> AsyncIterator[TelemetryRepository]:
    """Dependency to get a TelemetryRepository instance."""
    async for session in get_session():
        repo = TelemetryRepository(session)
        try:
            yield repo
            await session.commit()
        except Exception:  # pragma: no cover
            await session.rollback()
            raise


@router.post("", response_model=CredentialDetail, status_code=status.HTTP_201_CREATED)
async def create_or_update_credential(
    payload: CredentialCreate,
    current_user: User = Depends(get_current_user),
    repo: TelemetryRepository = Depends(get_repository),
) -> CredentialDetail:
    import logging
    logger = logging.getLogger(__name__)
    logger.info(
        f"create_or_update_credential: user_id={current_user.user_id}, email={current_user.email}, "
        f"provider={payload.provider}, name={payload.name}, type={payload.credential_type}"
    )
    try:
        credential = await repo.upsert_credential(payload, current_user.user_id)
        secret = await repo.get_credential_secret(credential)
        logger.info(
            f"create_or_update_credential: Successfully saved credential_id={credential.credential_id} "
            f"for user {current_user.user_id}"
        )
        return _to_detail(credential, secret=secret)
    except Exception as e:
        import logging
        from sqlalchemy.exc import IntegrityError
        
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to save credential for user {current_user.user_id}: {e}", exc_info=True)
        
        # Handle unique constraint violations
        if isinstance(e, IntegrityError) and "uq_credential_provider_name_type_user" in str(e):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A credential with provider '{payload.provider}', name '{payload.name}', and type '{payload.credential_type}' already exists. The credential has been updated with the new values."
            )
        
        # Re-raise HTTP exceptions as-is
        if isinstance(e, HTTPException):
            raise
        
        # Generic error
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save credential: {str(e)}"
        )


@router.get("", response_model=List[CredentialDetail])
async def list_credentials(
    provider: Optional[str] = Query(default=None),
    credential_type: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    repo: TelemetryRepository = Depends(get_repository),
) -> List[CredentialDetail]:
    credentials = await repo.list_credentials(user_id=current_user.user_id, provider=provider, credential_type=credential_type)
    details: List[CredentialDetail] = []
    for credential in credentials:
        secret = await repo.get_credential_secret(credential)
        details.append(_to_detail(credential, secret=secret))
    return details


@router.get("/with-secret", response_model=List[CredentialWithSecret])
async def list_credentials_with_secret(
    provider: Optional[str] = Query(default=None),
    credential_type: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    repo: TelemetryRepository = Depends(get_repository),
) -> List[CredentialWithSecret]:
    """List credentials with decrypted secrets for the current user.
    
    This avoids multiple per-credential fetches on the frontend and sidesteps
    greenlet/session issues observed when calling the single-credential endpoint
    repeatedly during initialization.
    """
    credentials = await repo.list_credentials(user_id=current_user.user_id, provider=provider, credential_type=credential_type)
    results: List[CredentialWithSecret] = []
    for credential in credentials:
        secret = await repo.get_credential_secret(credential)
        detail = _to_detail(credential, secret=secret)
        results.append(CredentialWithSecret(**detail.model_dump(), secret=secret))
    return results


@router.get("/{credential_id}", response_model=CredentialWithSecret)
async def get_credential(
    credential_id: UUID,
    current_user: User = Depends(get_current_user),
    repo: TelemetryRepository = Depends(get_repository),
) -> CredentialWithSecret:
    try:
        credential = await repo.get_credential(credential_id, current_user.user_id)
        if not credential:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
        
        # Ensure credential is refreshed and secret_ciphertext is loaded while in session
        try:
            await repo.session.refresh(credential, ['secret_ciphertext'])
        except Exception:
            pass  # If refresh fails, try to access directly
        
        # Access secret_ciphertext while still in session context
        from ..crypto import decrypt_secret
        ciphertext = credential.secret_ciphertext  # Access while in session
        secret = decrypt_secret(ciphertext)  # Decrypt synchronously (no DB access)
        
        # Touch credential (update last_used_at) - do this in a separate try/except to not fail the request
        try:
            await repo.touch_credential(credential_id)
        except Exception:
            pass  # Non-critical operation
        
        detail = _to_detail(credential, secret=secret)
        return CredentialWithSecret(**detail.model_dump(), secret=secret)
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error fetching credential {credential_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch credential: {str(e)}"
        )


@router.patch("/{credential_id}", response_model=CredentialDetail)
async def update_credential(
    credential_id: UUID,
    payload: CredentialUpdate,
    current_user: User = Depends(get_current_user),
    repo: TelemetryRepository = Depends(get_repository),
) -> CredentialDetail:
    try:
        credential = await repo.update_credential(credential_id, payload, current_user.user_id)
    except NoResultFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found") from None
    secret = await repo.get_credential_secret(credential)
    return _to_detail(credential, secret=secret)


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: UUID,
    current_user: User = Depends(get_current_user),
    repo: TelemetryRepository = Depends(get_repository),
) -> None:
    try:
        await repo.delete_credential(credential_id, current_user.user_id)
    except NoResultFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found") from None
