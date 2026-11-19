import hashlib

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from security_core.auth import validate_session


ALLOWED_ORIGINS = {
    "http://127.0.0.1:8002",
    "http://localhost:8002",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
}


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        method = request.method.upper()

        # Allow browser preflight requests.
        if method == "OPTIONS":
            return await call_next(request)

        # Public endpoints needed for health and initial login.
        if path in {
            "/",
            "/api/health",
            "/api/auth/status",
            "/api/auth/login",
        }:
            origin = request.headers.get("origin")
            if origin and origin not in ALLOWED_ORIGINS:
                return JSONResponse(
                    {"detail": "Origin not permitted."},
                    status_code=403
                )
            return await call_next(request)

        if not path.startswith("/api/"):
            return await call_next(request)

        origin = request.headers.get("origin")

        # Check browser origin on every API operation.
        if origin and origin not in ALLOWED_ORIGINS:
            return JSONResponse(
                {"detail": "Origin not permitted."},
                status_code=403
            )

        token = request.cookies.get("pyforge_session")
        csrf_token = request.headers.get("X-CSRF-Token")

        unsafe = method not in {"GET", "HEAD"}

        user = validate_session(
            token,
            csrf_token=csrf_token,
            require_csrf=unsafe
        )

        if user is None:
            return JSONResponse(
                {"detail": "Authentication required or session expired."},
                status_code=401
            )

        request.state.user = user

        return await call_next(request)
