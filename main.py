from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from configuration.config import APP_NAME, APP_VERSION
from projects.project_manager import (
    list_projects,
    get_project,
    create_project,
    rename_project,
    delete_project,
)
from projects.file_manager import (
    list_files,
    read_file,
    save_file,
    create_file,
    create_folder,
)

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Private Python development and server platform"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:8002",
        "http://localhost:8002",
    ],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)


class ProjectCreateRequest(BaseModel):
    name: str


class ProjectRenameRequest(BaseModel):
    new_name: str


class ProjectDeleteRequest(BaseModel):
    confirm: bool = False


class FileSaveRequest(BaseModel):
    path: str
    content: str = Field(..., max_length=1048576)


class FileCreateRequest(BaseModel):
    path: str
    content: str = Field(default="", max_length=1048576)


class FolderCreateRequest(BaseModel):
    path: str


@app.get("/")
def home():
    return {
        "platform": APP_NAME,
        "version": APP_VERSION,
        "message": "PyForge Cloud backend is running."
    }


@app.get("/api/health")
def health():
    return {
        "status": "online",
        "platform": APP_NAME,
        "version": APP_VERSION
    }


@app.get("/api/projects")
def projects():
    result = list_projects()
    return {"count": len(result), "projects": result}


@app.post("/api/projects", status_code=201)
def create_new_project(request: ProjectCreateRequest):
    try:
        return create_project(request.name)
    except FileExistsError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.get("/api/projects/{name}")
def project_details(name: str):
    try:
        project = get_project(name)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    return project


@app.get("/api/projects/{name}/files")
def project_files(name: str, directory: str = ""):
    try:
        return list_files(name, directory)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except (ValueError, NotADirectoryError) as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.get("/api/projects/{name}/file")
def open_project_file(name: str, path: str):
    try:
        return read_file(name, path)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.post("/api/projects/{name}/file", status_code=201)
def create_project_file(name: str, request: FileCreateRequest):
    try:
        return create_file(name, request.path, request.content)
    except FileExistsError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.post("/api/projects/{name}/folder", status_code=201)
def create_project_folder(name: str, request: FolderCreateRequest):
    try:
        return create_folder(name, request.path)
    except FileExistsError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.put("/api/projects/{name}/file")
def save_project_file(name: str, request: FileSaveRequest):
    try:
        return save_file(name, request.path, request.content)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.patch("/api/projects/{name}")
def rename_existing_project(name: str, request: ProjectRenameRequest):
    try:
        project = rename_project(name, request.new_name)
    except FileExistsError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    return project


@app.delete("/api/projects/{name}")
def delete_existing_project(name: str, request: ProjectDeleteRequest):
    try:
        deleted = delete_project(name, confirm=request.confirm)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")

    return {
        "success": True,
        "message": f"Project '{name}' deleted."
    }


# PYFORGE_CONSOLE_API_V2
from runtime.process_manager import (
    start_process,
    stop_process,
    restart_process,
    get_status,
    get_log_file,
)


class ConsoleRunRequest(BaseModel):
    project: str
    script: str | None = None


@app.get("/api/console/status")
def console_status():
    return get_status()


@app.post("/api/console/start")
def console_start(request: ConsoleRunRequest):
    try:
        return start_process(request.project, request.script)
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error))


@app.post("/api/console/restart")
def console_restart(request: ConsoleRunRequest):
    try:
        return restart_process(request.project, request.script)
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error))


@app.post("/api/console/stop")
def console_stop():
    return stop_process()


@app.get("/api/console/logs/{run_id}")
def console_download_log(run_id: str):
    try:
        path = get_log_file(run_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))

    return FileResponse(
        path,
        media_type="text/plain",
        filename=path.name,
    )
