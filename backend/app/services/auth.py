"""Authentication use-cases: register, login, token refresh/rotation, logout.

Refresh tokens rotate on every use. If an already-rotated token is presented
again, the whole session family for that user is revoked (token-theft signal).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import (
    AuthenticationError,
    ConflictError,
    PermissionDeniedError,
    ValidationError,
)
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    verify_password,
)
from app.models.user import RefreshToken, User
from app.repositories.users import RefreshTokenRepository, UserRepository
from app.schemas.auth import TokenResponse
from app.services.audit import record_audit

log = get_logger(__name__)

# Verified against when the email is unknown so response time doesn't reveal
# which accounts exist.
_DUMMY_HASH = hash_password("timing-equalizer-not-a-real-password")


@dataclass(frozen=True, slots=True)
class ClientInfo:
    user_agent: str = ""
    ip_address: str = ""


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.tokens = RefreshTokenRepository(session)

    async def register(
        self, email: str, password: str, full_name: str, client: ClientInfo
    ) -> tuple[User, TokenResponse]:
        if not self.settings.allow_registration:
            raise PermissionDeniedError("Registration is disabled on this server.")
        email = email.lower()
        if await self.users.get_by_email(email):
            raise ConflictError(
                "An account with this email already exists.", hint="Try signing in instead."
            )
        user = await self.users.add(
            User(email=email, full_name=full_name.strip(), password_hash=hash_password(password))
        )
        await record_audit(
            self.session, "user.register", user_id=user.id, ip_address=client.ip_address
        )
        tokens = await self._issue_tokens(user, client)
        log.info("user_registered", user_id=str(user.id))
        return user, tokens

    async def login(self, email: str, password: str, client: ClientInfo) -> TokenResponse:
        user = await self.users.get_by_email(email)
        if user is None or user.password_hash is None:
            verify_password(password, _DUMMY_HASH)
            raise AuthenticationError("Incorrect email or password.")
        if not verify_password(password, user.password_hash):
            await record_audit(
                self.session, "user.login_failed", user_id=user.id, ip_address=client.ip_address
            )
            await self.session.commit()  # keep the audit entry despite the error below
            raise AuthenticationError("Incorrect email or password.")
        if not user.is_active:
            raise PermissionDeniedError("This account has been deactivated.")
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        user.last_login_at = datetime.now(UTC)
        await record_audit(
            self.session, "user.login", user_id=user.id, ip_address=client.ip_address
        )
        return await self._issue_tokens(user, client)

    async def refresh(self, raw_token: str, client: ClientInfo) -> TokenResponse:
        now = datetime.now(UTC)
        stored = await self.tokens.get_by_hash(hash_refresh_token(raw_token))
        if stored is None:
            raise AuthenticationError("Your session has expired. Please sign in again.")
        if stored.revoked_at is not None:
            if stored.replaced_by_id is not None:
                # A rotated token was replayed: assume theft and end every session.
                await self.tokens.revoke_all(stored.user_id, now)
                await record_audit(
                    self.session,
                    "auth.refresh_token_reuse",
                    user_id=stored.user_id,
                    ip_address=client.ip_address,
                )
                log.warning("refresh_token_reuse_detected", user_id=str(stored.user_id))
                # Persist the revocation even though this request fails.
                await self.session.commit()
            raise AuthenticationError("Your session has expired. Please sign in again.")
        if _as_utc(stored.expires_at) <= now:
            raise AuthenticationError("Your session has expired. Please sign in again.")

        user = await self.users.get(stored.user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("Your session has expired. Please sign in again.")

        tokens, new_record = await self._issue_tokens_with_record(user, client)
        stored.revoked_at = now
        stored.replaced_by_id = new_record.id
        return tokens

    async def logout(self, raw_token: str) -> None:
        stored = await self.tokens.get_by_hash(hash_refresh_token(raw_token))
        if stored is not None and stored.revoked_at is None:
            stored.revoked_at = datetime.now(UTC)
            await record_audit(self.session, "user.logout", user_id=stored.user_id)

    async def change_password(
        self, user: User, current: str, new: str, client: ClientInfo
    ) -> TokenResponse:
        if user.password_hash is None or not verify_password(current, user.password_hash):
            # 422 rather than 401: the session itself is still valid.
            raise ValidationError("Your current password is incorrect.")
        user.password_hash = hash_password(new)
        # Changing the password signs out every device; this one gets fresh tokens.
        await self.tokens.revoke_all(user.id, datetime.now(UTC))
        await record_audit(self.session, "user.password_changed", user_id=user.id)
        return await self._issue_tokens(user, client)

    async def _issue_tokens(self, user: User, client: ClientInfo) -> TokenResponse:
        tokens, _ = await self._issue_tokens_with_record(user, client)
        return tokens

    async def _issue_tokens_with_record(
        self, user: User, client: ClientInfo
    ) -> tuple[TokenResponse, RefreshToken]:
        access_token, expires_at = create_access_token(user.id, self.settings)
        raw_refresh = generate_refresh_token()
        record = await self.tokens.add(
            RefreshToken(
                user_id=user.id,
                token_hash=hash_refresh_token(raw_refresh),
                expires_at=datetime.now(UTC) + timedelta(days=self.settings.refresh_token_ttl_days),
                user_agent=client.user_agent[:400],
                ip_address=client.ip_address[:64],
            )
        )
        return (
            TokenResponse(
                access_token=access_token, refresh_token=raw_refresh, expires_at=expires_at
            ),
            record,
        )


def _as_utc(value: datetime) -> datetime:
    """SQLite drops tzinfo on round-trip; treat naive datetimes as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)
