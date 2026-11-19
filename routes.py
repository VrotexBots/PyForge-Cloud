from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from security_core import auth


router = APIRouter(prefix="/api/auth", tags=["Security"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


def client_key(request):
    if request.client:
        return request.client.host
    return "unknown"


@router.get("/status")
def security_status():
    return {
        "owner_configured": auth.owner_exists(),
        "authentication": "enabled"
    }


@router.post("/login")
def owner_login(data: LoginRequest, request: Request, response: Response):
    try:
        result = auth.login(
            data.username,
            data.password,
            client_key(request)
        )
    except PermissionError as error:
        raise HTTPException(status_code=401, detail=str(error))
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error))

    secure_cookie = request.url.scheme == "https"

    response.set_cookie(
        key="pyforge_session",
        value=result["token"],
        max_age=12 * 60 * 60,
        httponly=True,
        secure=secure_cookie,
        samesite="strict",
        path="/"
    )

    return {
        "authenticated": True,
        "username": result["username"],
        "csrf_token": result["csrf_token"],
        "expires_at": result["expires_at"]
    }


@router.get("/me")
def current_owner(request: Request):
    user = getattr(request.state, "user", None)

    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    return {
        "authenticated": True,
        "username": user["username"],
        "expires_at": user["expires_at"]
    }


@router.post("/logout")
def owner_logout(request: Request, response: Response):
    token = request.cookies.get("pyforge_session")

    auth.logout(token, client_key(request))

    response.delete_cookie(
        key="pyforge_session",
        path="/",
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict"
    )

    return {"authenticated": False, "message": "Logged out."}
