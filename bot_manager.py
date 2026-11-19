import json
import os
import re
import threading
import subprocess
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from configuration.config import PROJECTS_DIR, BASE_DIR
from projects.project_manager import safe_project_path
from projects.file_manager import safe_file_path
from runtime.process_manager import (
    start_process,
    stop_process,
    restart_process,
    get_status,
    get_run_history,
)

router = APIRouter(prefix="/api/bot-manager", tags=["Bot Manager"])

DATA_DIR = BASE_DIR / "runtime"
DATA_FILE = DATA_DIR / "bot_manager.json"
LOCK = threading.RLock()

NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")
APP_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

DEFAULT_SERVER_ID = "local"
DEFAULT_SERVER = {
    "id": DEFAULT_SERVER_ID,
    "name": "Local Android Server",
    "type": "local",
    "description": "Local PyForge runtime on this Android device.",
    "created_at": None,
}

RESTART_POLICIES = {"never", "on_failure", "always"}
APP_TYPES = {"web_app", "api", "worker", "bot", "scheduled_job"}
FRAMEWORKS = {"plain_python", "fastapi", "flask"}


def now():
    return datetime.now(timezone.utc).isoformat()


def load_data():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not DATA_FILE.exists():
        return {
            "servers": [dict(DEFAULT_SERVER, created_at=now())],
            "applications": [],
            "version": 1,
        }

    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RuntimeError(
            "Bot Manager configuration could not be read. "
            "The original file has not been overwritten."
        )

    if not isinstance(data, dict):
        raise RuntimeError("Bot Manager configuration has an invalid format.")

    data.setdefault("servers", [])
    data.setdefault("applications", [])
    data.setdefault("version", 1)

    if not any(s.get("id") == DEFAULT_SERVER_ID for s in data["servers"]):
        data["servers"].insert(0, dict(DEFAULT_SERVER, created_at=now()))

    return data


def save_data(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = DATA_FILE.with_suffix(".tmp")

    temporary.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )

    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass

    temporary.replace(DATA_FILE)

    try:
        os.chmod(DATA_FILE, 0o600)
    except OSError:
        pass


def validate_name(value, label="Name"):
    value = value.strip() if isinstance(value, str) else ""

    if not NAME_PATTERN.fullmatch(value):
        raise HTTPException(
            status_code=400,
            detail=f"{label} must be 1–64 characters and use letters, numbers, spaces, dots, underscores or hyphens.",
        )

    return value


def validate_server(data, server_id):
    for server in data["servers"]:
        if server["id"] == server_id:
            return server

    raise HTTPException(status_code=404, detail="Server group not found.")


def validate_app(data, app_id):
    if not APP_ID_PATTERN.fullmatch(app_id):
        raise HTTPException(status_code=400, detail="Invalid application ID.")

    for app in data["applications"]:
        if app["id"] == app_id:
            return app

    raise HTTPException(status_code=404, detail="Application not found.")


def validate_project(project):
    try:
        root = safe_project_path(project)
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=400, detail=str(error))

    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Project folder not found.")

    return root


def validate_entrypoint(project, entrypoint):
    if not isinstance(entrypoint, str) or not entrypoint.strip():
        raise HTTPException(status_code=400, detail="An entry point is required.")

    try:
        root, path = safe_file_path(project, entrypoint)
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=400, detail=str(error))

    if not path.is_file() or path.suffix.lower() != ".py":
        raise HTTPException(
            status_code=400,
            detail="The entry point must be an existing Python (.py) file.",
        )

    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise HTTPException(status_code=400, detail="Unsafe entry-point path.")

    return path.relative_to(root).as_posix()


def public_app(app):
    project = app["project"]

    try:
        status = get_status(project)
    except Exception:
        status = {"status": "unknown", "run_id": None, "log_url": None}

    return {
        **app,
        "runtime_status": status.get("status", "unknown"),
        "run_id": status.get("run_id"),
        "log_url": status.get("log_url"),
        "runtime_seconds": status.get("runtime_seconds", 0),
        "last_started_at": status.get("started_at"),
        "last_ended_at": status.get("ended_at"),
        "return_code": status.get("return_code"),
        "output": status.get("output", [])[-15:],
    }


class ServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=300)


class ServerUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=300)


class ApplicationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    server_id: str = DEFAULT_SERVER_ID
    project: str
    entrypoint: str = "main.py"
    language: str = "python"
    framework: str = "plain_python"
    application_type: str = "bot"
    startup_command: str = ""
    command_mode: str = "automatic"
    working_directory: str = "."
    application_url: str = ""
    port: int | None = Field(default=None, ge=1, le=65535)
    python_interpreter: str = "system"
    auto_start: bool = False
    restart_policy: str = "never"
    max_restart_attempts: int = Field(default=3, ge=0, le=10)
    restart_backoff_seconds: int = Field(default=30, ge=5, le=3600)
    environment_keys: list[str] = Field(default_factory=list)


class ApplicationUpdate(ApplicationCreate):
    pass


def validate_application_fields(data, values):
    name = validate_name(values.name, "Application name")
    validate_server(data, values.server_id)

    if values.language != "python":
        raise HTTPException(
            status_code=400,
            detail="Python is the currently supported runtime.",
        )

    if values.framework not in FRAMEWORKS:
        raise HTTPException(status_code=400, detail="Unsupported framework.")

    if values.application_type not in APP_TYPES:
        raise HTTPException(status_code=400, detail="Invalid application type.")

    if values.restart_policy not in RESTART_POLICIES:
        raise HTTPException(status_code=400, detail="Invalid restart policy.")

    if values.command_mode not in {"automatic", "manual"}:
        raise HTTPException(status_code=400, detail="Invalid command mode.")

    if values.python_interpreter != "system":
        raise HTTPException(
            status_code=400,
            detail="Only the system Python interpreter is enabled in this version.",
        )

    # The existing Console process manager launches from the project root.
    if values.working_directory not in ("", "."):
        raise HTTPException(
            status_code=400,
            detail="This version uses the project root as its working directory.",
        )

    project_root = validate_project(values.project)
    entrypoint = validate_entrypoint(values.project, values.entrypoint)

    # One registered application per project prevents process-name collisions
    # in the existing Console process manager.
    for existing in data["applications"]:
        if existing["project"] == values.project:
            raise HTTPException(
                status_code=409,
                detail="This project is already registered in Bot Manager.",
            )

    command = values.startup_command.strip()

    if values.command_mode == "automatic":
        command = f"python {entrypoint}"

    if not command:
        raise HTTPException(status_code=400, detail="Startup command is required.")

    if len(command) > 500:
        raise HTTPException(status_code=400, detail="Startup command is too long.")

    keys = []
    for key in values.environment_keys:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", key):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid environment variable name: {key}",
            )
        if key not in keys:
            keys.append(key)

    return {
        "name": name,
        "server_id": values.server_id,
        "project": values.project,
        "entrypoint": entrypoint,
        "language": "python",
        "framework": values.framework,
        "application_type": values.application_type,
        "startup_command": command,
        "command_mode": values.command_mode,
        "working_directory": ".",
        "application_url": values.application_url.strip(),
        "port": values.port,
        "python_interpreter": "system",
        "auto_start": values.auto_start,
        "restart_policy": values.restart_policy,
        "max_restart_attempts": values.max_restart_attempts,
        "restart_backoff_seconds": values.restart_backoff_seconds,
        "environment_keys": keys,
    }


@router.get("/servers")
def list_servers():
    with LOCK:
        data = load_data()
        save_data(data)

        result = []
        for server in data["servers"]:
            apps = [
                app for app in data["applications"]
                if app["server_id"] == server["id"]
            ]

            result.append({
                **server,
                "application_count": len(apps),
            })

        return {"servers": result}


@router.post("/servers", status_code=201)
def create_server(request: ServerCreate):
    with LOCK:
        data = load_data()
        name = validate_name(request.name, "Server name")

        if any(s["name"].lower() == name.lower() for s in data["servers"]):
            raise HTTPException(status_code=409, detail="Server name already exists.")

        server = {
            "id": uuid4().hex,
            "name": name,
            "type": "logical",
            "description": request.description,
            "created_at": now(),
        }

        data["servers"].append(server)
        save_data(data)
        return server


@router.patch("/servers/{server_id}")
def update_server(server_id: str, request: ServerUpdate):
    with LOCK:
        data = load_data()
        server = validate_server(data, server_id)

        name = validate_name(request.name, "Server name")

        if any(
            s["id"] != server_id and s["name"].lower() == name.lower()
            for s in data["servers"]
        ):
            raise HTTPException(status_code=409, detail="Server name already exists.")

        server["name"] = name
        server["description"] = request.description
        save_data(data)
        return server


@router.delete("/servers/{server_id}")
def delete_server(server_id: str):
    if server_id == DEFAULT_SERVER_ID:
        raise HTTPException(status_code=400, detail="The local server cannot be deleted.")

    with LOCK:
        data = load_data()
        validate_server(data, server_id)

        if any(a["server_id"] == server_id for a in data["applications"]):
            raise HTTPException(
                status_code=409,
                detail="Move or remove its applications before deleting this server.",
            )

        data["servers"] = [
            s for s in data["servers"] if s["id"] != server_id
        ]
        save_data(data)
        return {"ok": True}


@router.get("/applications")
def list_applications():
    with LOCK:
        data = load_data()
        return {
            "applications": [
                public_app(app) for app in data["applications"]
            ]
        }


@router.post("/applications", status_code=201)
def create_application(request: ApplicationCreate):
    with LOCK:
        data = load_data()
        fields = validate_application_fields(data, request)

        app = {
            "id": uuid4().hex,
            **fields,
            "created_at": now(),
            "updated_at": now(),
        }

        data["applications"].append(app)
        save_data(data)
        return public_app(app)


@router.get("/applications/{app_id}")
def get_application(app_id: str):
    with LOCK:
        data = load_data()
        app = validate_app(data, app_id)
        return public_app(app)


@router.put("/applications/{app_id}")
def update_application(app_id: str, request: ApplicationUpdate):
    with LOCK:
        data = load_data()
        app = validate_app(data, app_id)

        fields = validate_application_fields(
            {
                **data,
                "applications": [
                    item for item in data["applications"]
                    if item["id"] != app_id
                ],
            },
            request,
        )

        status = get_status(app["project"])
        if status.get("status") in ("running", "starting", "stopping"):
            raise HTTPException(
                status_code=409,
                detail="Stop the application before changing its configuration.",
            )

        app.update(fields)
        app["updated_at"] = now()
        save_data(data)
        return public_app(app)


@router.delete("/applications/{app_id}")
def delete_application(app_id: str):
    with LOCK:
        data = load_data()
        app = validate_app(data, app_id)

        status = get_status(app["project"])
        if status.get("status") in ("running", "starting", "stopping"):
            raise HTTPException(
                status_code=409,
                detail="Stop the application before removing it.",
            )

        data["applications"] = [
            item for item in data["applications"]
            if item["id"] != app_id
        ]

        save_data(data)
        return {"ok": True}


@router.post("/applications/{app_id}/start")
def start_application(app_id: str):
    with LOCK:
        data = load_data()
        app = validate_app(data, app_id)

        validate_project(app["project"])
        entrypoint = validate_entrypoint(app["project"], app["entrypoint"])

        try:
            return start_process(app["project"], entrypoint)
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error))
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error))
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))


@router.post("/applications/{app_id}/stop")
def stop_application(app_id: str):
    with LOCK:
        data = load_data()
        app = validate_app(data, app_id)
        return stop_process(app["project"])


@router.post("/applications/{app_id}/restart")
def restart_application(app_id: str):
    with LOCK:
        data = load_data()
        app = validate_app(data, app_id)

        validate_project(app["project"])
        entrypoint = validate_entrypoint(app["project"], app["entrypoint"])

        try:
            return restart_process(app["project"], entrypoint)
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error))
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error))
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))


class BotCommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=500)



@router.post("/applications/{app_id}/command")
def run_application_command(app_id: str, request: BotCommandRequest):
    with LOCK:
        data = load_data()
        app = validate_app(data, app_id)
        root = validate_project(app["project"])

    try:
        parts = shlex.split(request.command)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=f"Invalid command: {error}")

    if len(parts) < 2 or parts[0].lower() not in ("python", "python3"):
        raise HTTPException(status_code=400, detail="Use: python script.py [arguments]")

    script_name = parts[1]
    arguments = parts[2:]
    if script_name == "-u" and arguments:
        script_name = arguments[0]
        arguments = arguments[1:]

    if script_name.startswith("-"):
        raise HTTPException(status_code=400, detail="Python script filename required.")

    try:
        checked_root, script_path = safe_file_path(app["project"], script_name)
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=400, detail=str(error))

    if (not script_path.is_file()
        or script_path.suffix.lower() != ".py"
        or script_path.is_symlink()
        or not script_path.resolve().is_relative_to(checked_root.resolve())):
        raise HTTPException(status_code=400, detail="Script must be inside the selected project.")

    try:
        result = subprocess.run(
            [sys.executable, "-u", str(script_path), *arguments],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            shell=False,
        )
        output = result.stdout or ""
        if result.stderr:
            output += ("\n[STDERR]\n" if output else "[STDERR]\n") + result.stderr
        return {
            "ok": result.returncode == 0,
            "return_code": result.returncode,
            "output": (output or "(No output.)")[-20000:],
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "return_code": None,
            "output": "Command stopped: 30-second time limit reached.",
        }
    except OSError as error:
        raise HTTPException(status_code=500, detail=str(error))


@router.get("/applications/{app_id}/history")
def application_history(app_id: str):
    with LOCK:
        data = load_data()
        app = validate_app(data, app_id)
        return {
            "application": app["name"],
            "runs": get_run_history(app["project"]),
        }


@router.get("/projects")
def available_projects():
    try:
        from projects.project_manager import list_projects
        return {"projects": list_projects()}
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))
