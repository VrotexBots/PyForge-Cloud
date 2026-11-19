from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
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
    rename_item,
    duplicate_file,
    delete_item,
    create_project_zip,
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


class FileItemRenameRequest(BaseModel):
    path: str
    new_name: str


class FileItemPathRequest(BaseModel):
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



# PYFORGE_FILES_STUDIO_API_V1

@app.post("/api/projects/{name}/item/rename")
def rename_project_item(name: str, request: FileItemRenameRequest):
    try:
        return rename_item(name, request.path, request.new_name)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except FileExistsError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.post("/api/projects/{name}/item/duplicate")
def duplicate_project_file(name: str, request: FileItemRenameRequest):
    try:
        return duplicate_file(name, request.path, request.new_name)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except FileExistsError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.delete("/api/projects/{name}/item")
def delete_project_item(name: str, request: FileItemPathRequest):
    try:
        return delete_item(name, request.path)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.get("/api/projects/{name}/download")
def download_project_file(name: str, path: str):
    from projects.file_manager import safe_file_path

    try:
        root, file_path = safe_file_path(name, path)
        if not file_path.is_file():
            raise FileNotFoundError("File not found.")
        return FileResponse(
            path=str(file_path),
            filename=file_path.name,
            media_type="application/octet-stream"
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.get("/api/projects/{name}/download-zip")
def download_project_archive(name: str):
    try:
        archive = create_project_zip(name)
        return StreamingResponse(
            archive,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{name}.zip"'
            }
        )
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



# PYFORGE_CONSOLE_API_V3
from runtime.process_manager import (
    start_process,
    stop_process,
    restart_process,
    get_status,
    get_project_statuses,
    get_run_history,
    get_log_file,
)


class ConsoleRunRequest(BaseModel):
    project: str
    script: str | None = None


class ConsoleProjectRequest(BaseModel):
    project: str


@app.get("/api/console/projects")
def console_projects():
    return {
        "projects": get_project_statuses(list_projects())
    }


@app.get("/api/console/status")
def console_status():
    return get_status()


@app.get("/api/console/status/{project}")
def console_project_status(project: str):
    return get_status(project)


@app.get("/api/console/history/{project}")
def console_project_history(project: str):
    return {
        "project": project,
        "runs": get_run_history(project)
    }


@app.post("/api/console/start")
def console_start(request: ConsoleRunRequest):
    try:
        return start_process(request.project, request.script)
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.post("/api/console/restart")
def console_restart(request: ConsoleRunRequest):
    try:
        return restart_process(request.project, request.script)
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.post("/api/console/stop")
def console_stop(request: ConsoleProjectRequest):
    return stop_process(request.project)


@app.get("/api/console/logs/{run_id}")
def console_download_log(run_id: str):
    try:
        log_path = get_log_file(run_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))

    return FileResponse(
        log_path,
        media_type="text/plain",
        filename=log_path.name,
    )


# PYFORGE_SYSTEM_MONITORING_V1
from monitoring.system_monitor import get_system_summary


@app.get("/api/monitoring/summary")
def monitoring_summary():
    try:
        projects = get_project_statuses(list_projects())
        return get_system_summary(projects)
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Monitoring error: {str(error)}"
        )
