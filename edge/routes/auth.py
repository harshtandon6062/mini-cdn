"""User login: POST /auth/login returns a short-lived JWT with the user's role.

Rate limited (by IP, since the caller is not logged in yet) to slow down
password guessing. /admin/login is the same login, kept for older clients.
"""

from fastapi import APIRouter, Depends, HTTPException

from edge.auth import AuthService
from edge.dependencies import enforce_rate_limit, get_auth_service
from edge.models import LoginRequest, TokenResponse

router = APIRouter(tags=["auth"])


@router.post("/auth/login", dependencies=[Depends(enforce_rate_limit)])
@router.post("/admin/login", dependencies=[Depends(enforce_rate_limit)])
def login(body: LoginRequest, auth: AuthService = Depends(get_auth_service)) -> TokenResponse:
    """Swap a username + password for a signed JWT (401 if wrong)."""
    token = auth.login(body.username, body.password)
    if token is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return TokenResponse(
        access_token=token, role=auth.role_of(body.username), expires_in=auth.expiry_seconds
    )
