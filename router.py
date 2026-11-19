"""PyForge Coding Assistant - isolated secure router."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from coding_assistant import security, conversations


router = APIRouter(tags=["Coding Assistant"])

BASE_DIR = Path(__file__).resolve().parent
CHAT_PAGE = BASE_DIR / "chat.html"

SESSION_COOKIE = "coding_assistant_session"
SESSION_MAX_AGE = 12 * 60 * 60


class PasswordSetupRequest(BaseModel):
    password: str = Field(..., min_length=8, max_length=8)


class AssistantLoginRequest(BaseModel):
    password: str = Field(..., min_length=8, max_length=8)


class ConversationCreateRequest(BaseModel):
    title: str = Field(
        default="New conversation",
        min_length=1,
        max_length=120
    )
    project_name: str | None = Field(
        default=None,
        max_length=120
    )


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=50000)
    conversation_id: str | None = None


def client_key(request: Request) -> str:
    if request.client:
        return request.client.host[:128]
    return "unknown"


def require_assistant_session(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    session = security.validate_session(token)

    if not session:
        raise HTTPException(
            status_code=401,
            detail="Coding Assistant login required."
        )

    return session


@router.get(
    "/api/coding-assistant/page",
    include_in_schema=False
)
def assistant_page():
    if not CHAT_PAGE.is_file():
        raise HTTPException(
            status_code=404,
            detail="Coding Assistant interface is missing."
        )

    return FileResponse(
        CHAT_PAGE,
        media_type="text/html",
        headers={"Cache-Control": "no-store"}
    )


@router.get("/api/coding-assistant/status")
def assistant_status(request: Request):
    session = security.validate_session(
        request.cookies.get(SESSION_COOKIE)
    )

    return {
        "password_configured": security.is_configured(),
        "authenticated": bool(session),
        "ai_ready": False,
        "ai_message": "AI generation service is not connected yet."
    }


@router.post("/api/coding-assistant/setup")
def assistant_setup(
    data: PasswordSetupRequest,
    request: Request
):
    if security.is_configured():
        raise HTTPException(
            status_code=409,
            detail="The Coding Assistant password is already configured."
        )

    try:
        security.configure_password(data.password)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error))

    return {"password_configured": True}


@router.post("/api/coding-assistant/login")
def assistant_login(
    data: AssistantLoginRequest,
    request: Request,
    response: Response
):
    try:
        result = security.login(
            data.password,
            client_key=client_key(request)
        )
    except PermissionError as error:
        raise HTTPException(status_code=401, detail=str(error))
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error))

    response.set_cookie(
        key=SESSION_COOKIE,
        value=result["token"],
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/"
    )

    return {
        "authenticated": True,
        "expires_at": result["expires_at"]
    }


@router.post("/api/coding-assistant/logout")
def assistant_logout(
    request: Request,
    response: Response
):
    security.logout(
        request.cookies.get(SESSION_COOKIE)
    )

    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict"
    )

    return {"authenticated": False}


@router.get("/api/coding-assistant/conversations")
def assistant_conversations(request: Request):
    require_assistant_session(request)

    return {
        "conversations": conversations.list_conversations()
    }


@router.post(
    "/api/coding-assistant/conversations",
    status_code=201
)
def create_assistant_conversation(
    data: ConversationCreateRequest,
    request: Request
):
    require_assistant_session(request)

    title = data.title.strip() or "New conversation"

    conversation_id = conversations.create_conversation(
        title=title,
        project_name=data.project_name
    )

    return {
        "conversation_id": conversation_id,
        "title": title
    }


@router.get(
    "/api/coding-assistant/conversations/{conversation_id}/messages"
)
def assistant_messages(
    conversation_id: str,
    request: Request
):
    require_assistant_session(request)

    conversation = conversations.get_conversation(
        conversation_id
    )

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found."
        )

    return {
        "conversation": conversation,
        "messages": conversations.get_messages(conversation_id)
    }


@router.post("/api/coding-assistant/chat")
def assistant_chat(
    data: ChatRequest,
    request: Request
):
    require_assistant_session(request)

    raise HTTPException(
        status_code=503,
        detail=(
            "The secure Coding Assistant is installed, "
            "but its AI generation service is not connected yet."
        )
    )
