"""Access-token verification. Returns the verified auth subject and claims.

Kept separate from routes and DB so the identity provider can be swapped (e.g. JWKS/OIDC)
without touching tenant-guard logic.
"""

import jwt

from app.core.config import Settings
from app.core.errors import ApiError

MIN_SECRET_BYTES = 32


class TokenIdentity(str):
    """String subclass representing the verified auth subject, with optional token claims."""

    email: str | None
    display_name: str | None
    scope: str | None

    def __new__(
        cls,
        subject: str,
        email: str | None = None,
        display_name: str | None = None,
        scope: str | None = None,
    ) -> "TokenIdentity":
        obj = super().__new__(cls, subject)
        obj.email = email
        obj.display_name = display_name
        obj.scope = scope
        return obj

    @property
    def subject(self) -> str:
        return str(self)


def _unauthenticated(message: str = "Authentication required.") -> ApiError:
    return ApiError(401, "UNAUTHENTICATED", message)


def verify_access_token(token: str, settings: Settings) -> TokenIdentity:
    """Validate signature, expiry and optional issuer/audience; return the `sub` claim.

    Fails closed: a missing or weak secret rejects every token.
    """
    secret = settings.auth_jwt_secret.get_secret_value() if settings.auth_jwt_secret else ""
    if len(secret.encode()) < MIN_SECRET_BYTES:
        raise _unauthenticated()
    options: dict[str, object] = {"require": ["exp", "sub"]}
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[settings.auth_jwt_algorithm],  # pinned; never read from the token
            issuer=settings.auth_jwt_issuer,
            audience=settings.auth_jwt_audience,
            options=options,  # type: ignore[arg-type]
        )
    except jwt.PyJWTError:
        raise _unauthenticated("Invalid or expired token.") from None
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise _unauthenticated("Invalid or expired token.")

    raw_email = claims.get("email")
    email = raw_email if isinstance(raw_email, str) else None
    raw_name = claims.get("name") or claims.get("display_name")
    display_name = raw_name if isinstance(raw_name, str) else None
    raw_scope = claims.get("scope")
    scope = raw_scope if isinstance(raw_scope, str) else None

    return TokenIdentity(subject=subject, email=email, display_name=display_name, scope=scope)
