"""Shared FastAPI dependencies (DI wiring for sessions, settings, auth, services)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.errors import AuthenticationError, RateLimitedError
from app.core.rate_limit import InMemoryRateLimiter, RateLimiter, RedisRateLimiter
from app.core.redis import get_redis
from app.core.security import InvalidTokenError, decode_access_token
from app.models.user import User
from app.repositories.users import UserRepository
from app.services.auth import AuthService, ClientInfo
from app.services.documents import DocumentService
from app.services.jobs import JobService
from app.services.llm.user_models import activate, load_user_model
from app.services.storage import get_storage
from app.workers.dispatcher import get_dispatcher

SettingsDep = Annotated[Settings, Depends(get_settings)]
# scope="function": commit before the response is sent, so a failed commit
# surfaces as an error instead of a false success.
DbSession = Annotated[AsyncSession, Depends(get_db, scope="function")]

_bearer = HTTPBearer(auto_error=False)
_memory_limiter = InMemoryRateLimiter()


def get_rate_limiter(settings: SettingsDep) -> RateLimiter:
    redis = get_redis(settings)
    return RedisRateLimiter(redis) if redis is not None else _memory_limiter


def client_info(request: Request) -> ClientInfo:
    return ClientInfo(
        user_agent=request.headers.get("user-agent", ""),
        ip_address=request.client.host if request.client else "",
    )


async def get_current_user(
    db: DbSession,
    settings: SettingsDep,
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise AuthenticationError("Please sign in to continue.")
    try:
        claims = decode_access_token(credentials.credentials, settings)
    except InvalidTokenError as exc:
        raise AuthenticationError("Your session has expired. Please sign in again.") from exc
    user = await UserRepository(db).get(claims.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Your session has expired. Please sign in again.")
    request.state.user_id = str(user.id)
    # Their AI work runs on the model they chose in Settings → AI (or the server's default).
    # Each request is its own task, so this doesn't outlive the request.
    activate(await load_user_model(db, user.id))
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def rate_limit(bucket: str, per_minute_setting: str = "rate_limit_per_minute"):  # type: ignore[no-untyped-def]
    """Dependency factory: limit requests per client IP for the given bucket."""

    async def dependency(
        request: Request,
        settings: SettingsDep,
        limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    ) -> None:
        if not settings.rate_limit_enabled:
            return
        limit = int(getattr(settings, per_minute_setting))
        client = request.client.host if request.client else "unknown"
        allowed, reset_in = await limiter.hit(f"{bucket}:{client}", limit)
        if not allowed:
            raise RateLimitedError(
                "Too many requests. Please slow down.",
                hint=f"Try again in {reset_in} seconds.",
                details={"retry_after": reset_in},
            )

    return dependency


def get_auth_service(db: DbSession, settings: SettingsDep) -> AuthService:
    return AuthService(db, settings)


def get_job_service(db: DbSession, settings: SettingsDep) -> JobService:
    return JobService(db, get_dispatcher(settings))


def get_document_service(db: DbSession, settings: SettingsDep) -> DocumentService:
    return DocumentService(db, settings, get_storage(settings), get_job_service(db, settings))


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
JobServiceDep = Annotated[JobService, Depends(get_job_service)]
DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]
ClientInfoDep = Annotated[ClientInfo, Depends(client_info)]
