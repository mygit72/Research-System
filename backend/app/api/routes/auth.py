"""Auth endpoints.

Browsers receive the refresh token as an httpOnly, SameSite=Strict cookie scoped
to the auth path, so JavaScript never has to store it (XSS-resistant). The
access token is short-lived and kept in memory by the SPA. Non-browser API
clients can instead send the refresh token in the request body.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response, status

from app.api.deps import (
    AuthServiceDep,
    ClientInfoDep,
    CurrentUser,
    SettingsDep,
    rate_limit,
)
from app.core.config import Settings
from app.core.errors import AuthenticationError
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.schemas.common import ErrorResponse

REFRESH_COOKIE = "ri_refresh"

router = APIRouter(prefix="/auth", tags=["auth"], responses={429: {"model": ErrorResponse}})
# Endpoints that take a password get the strict brute-force limit. Refresh and logout don't:
# refresh runs on every page load, and sharing the bucket logged people out after ~10 reloads
# (or a few tabs) in a minute; refresh tokens are single-use and rotated, so the general API
# limit is enough there.
CREDENTIALS_LIMIT = [Depends(rate_limit("auth", "auth_rate_limit_per_minute"))]
SESSION_LIMIT = [Depends(rate_limit("auth-session"))]


class RegisterResponse(TokenResponse):
    user: UserResponse


def _set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=int(timedelta(days=settings.refresh_token_ttl_days).total_seconds()),
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
        path=f"{settings.api_prefix}/auth",
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=f"{settings.api_prefix}/auth")


def _resolve_refresh_token(body: RefreshRequest | None, cookie: str | None) -> str:
    token = (body.refresh_token if body else None) or cookie
    if not token:
        raise AuthenticationError("Please sign in to continue.")
    return token


RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=CREDENTIALS_LIMIT,
)
async def register(
    body: RegisterRequest,
    auth: AuthServiceDep,
    client: ClientInfoDep,
    response: Response,
    settings: SettingsDep,
) -> RegisterResponse:
    user, tokens = await auth.register(body.email, body.password, body.full_name, client)
    _set_refresh_cookie(response, tokens.refresh_token, settings)
    return RegisterResponse(**tokens.model_dump(), user=UserResponse.model_validate(user))


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={401: {"model": ErrorResponse}},
    dependencies=CREDENTIALS_LIMIT,
)
async def login(
    body: LoginRequest,
    auth: AuthServiceDep,
    client: ClientInfoDep,
    response: Response,
    settings: SettingsDep,
) -> TokenResponse:
    tokens = await auth.login(body.email, body.password, client)
    _set_refresh_cookie(response, tokens.refresh_token, settings)
    return tokens


@router.post(
    "/refresh",
    response_model=TokenResponse,
    responses={401: {"model": ErrorResponse}},
    dependencies=SESSION_LIMIT,
)
async def refresh(
    auth: AuthServiceDep,
    client: ClientInfoDep,
    response: Response,
    settings: SettingsDep,
    cookie: RefreshCookie = None,
    body: RefreshRequest | None = None,
) -> TokenResponse:
    tokens = await auth.refresh(_resolve_refresh_token(body, cookie), client)
    _set_refresh_cookie(response, tokens.refresh_token, settings)
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=SESSION_LIMIT)
async def logout(
    auth: AuthServiceDep,
    response: Response,
    settings: SettingsDep,
    cookie: RefreshCookie = None,
    body: RefreshRequest | None = None,
) -> None:
    token = (body.refresh_token if body else None) or cookie
    if token:
        await auth.logout(token)
    _clear_refresh_cookie(response, settings)


@router.post("/change-password", response_model=TokenResponse, dependencies=CREDENTIALS_LIMIT)
async def change_password(
    body: ChangePasswordRequest,
    user: CurrentUser,
    auth: AuthServiceDep,
    client: ClientInfoDep,
    response: Response,
    settings: SettingsDep,
) -> TokenResponse:
    """Changes the password, signs out all other sessions, and returns fresh tokens."""
    tokens = await auth.change_password(user, body.current_password, body.new_password, client)
    _set_refresh_cookie(response, tokens.refresh_token, settings)
    return tokens
