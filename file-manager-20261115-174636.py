from pathlib import Path, PurePosixPath
from datetime import datetime
import shutil

from configuration.config import PROJECTS_DIR, BASE_DIR

MAX_FILE_SIZE = 1024 * 1024
IGNORED = {"__pycache__", ".git", ".venv", "venv", "node_modules"}


def project_root(name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Invalid project name.")

    if name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("Invalid project name.")

    root = PROJECTS_DIR.resolve()
    candidate = PROJECTS_DIR / name

    if candidate.is_symlink() or not candidate.is_dir():
        raise FileNotFoundError("Project not found.")

    resolved = candidate.resolve(strict=True)

    if resolved.parent != root:
        raise ValueError("Invalid project location.")

    return resolved


def safe_file_path(name, relative_path):
    root = project_root(name)

    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError("A file path is required.")

    relative = PurePosixPath(relative_path)

    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Invalid file path.")

    current = root

    for part in relative.parts:
        if part in {"", "."}:
            continue

        if part in IGNORED:
            raise ValueError("This folder is protected.")

        current = current / part

        if current.is_symlink():
            raise ValueError("Symbolic links are not allowed.")

    resolved = current.resolve(strict=False)

    if not resolved.is_relative_to(root):
        raise ValueError("Path is outside the project.")

    return root, resolved


def validate_new_name(name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("A name is required.")

    if name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("Use a single file or folder name.")

    if name.startswith(" ") or name.endswith(" "):
        raise ValueError("Names cannot start or end with spaces.")

    if any(ord(char) < 32 for char in name):
        raise ValueError("Invalid characters in name.")

    if len(name) > 128:
        raise ValueError("Name is too long.")

    if name in IGNORED:
        raise ValueError("This name is reserved.")

    return name


def list_files(name, directory=""):
    root = project_root(name)

    if directory:
        _, folder = safe_file_path(name, directory)
    else:
        folder = root

    if not folder.is_dir():
        raise NotADirectoryError("Folder not found.")

    entries = []

    for item in sorted(
        folder.iterdir(),
        key=lambda p: (not p.is_dir(), p.name.lower())
    ):
        if item.is_symlink() or item.name in IGNORED:
            continue

        entries.append({
            "name": item.name,
            "type": "folder" if item.is_dir() else "file",
            "path": item.relative_to(root).as_posix()
        })

    return {
        "project": name,
        "directory": directory,
        "entries": entries
    }


def read_file(name, relative_path):
    root, path = safe_file_path(name, relative_path)

    if not path.is_file():
        raise FileNotFoundError("File not found.")

    if path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError("File exceeds the 1 MB editor limit.")

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ValueError("This is not a supported UTF-8 text file.")

    return {
        "project": name,
        "path": path.relative_to(root).as_posix(),
        "content": content
    }


def create_file(name, relative_path, content=""):
    if not isinstance(content, str):
        raise ValueError("File content must be text.")

    if len(content.encode("utf-8")) > MAX_FILE_SIZE:
        raise ValueError("File exceeds the 1 MB editor limit.")

    root, path = safe_file_path(name, relative_path)

    if not path.parent.is_dir():
        raise FileNotFoundError("Parent folder does not exist.")

    try:
        with path.open("x", encoding="utf-8") as file:
            file.write(content)
    except FileExistsError:
        raise FileExistsError("A file or folder with this name already exists.")

    return {
        "success": True,
        "path": path.relative_to(root).as_posix(),
        "message": "File created successfully."
    }


def create_folder(name, relative_path):
    root, path = safe_file_path(name, relative_path)

    if not path.parent.is_dir():
        raise FileNotFoundError("Parent folder does not exist.")

    try:
        path.mkdir()
    except FileExistsError:
        raise FileExistsError("A file or folder with this name already exists.")

    return {
        "success": True,
        "path": path.relative_to(root).as_posix(),
        "message": "Folder created successfully."
    }


def save_file(name, relative_path, content):
    if not isinstance(content, str):
        raise ValueError("File content must be text.")

    encoded = content.encode("utf-8")

    if len(encoded) > MAX_FILE_SIZE:
        raise ValueError("File exceeds the 1 MB editor limit.")

    root, path = safe_file_path(name, relative_path)

    if not path.is_file():
        raise FileNotFoundError("File not found. Create it first.")

    try:
        path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ValueError("Cannot overwrite a non-text file.")

    backup_path = None

    backup_root = (
        BASE_DIR / "backup_factory" / "file_edits" / name
    )
    backup_root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    relative = path.relative_to(root)
    backup_path = backup_root / (str(relative) + "." + timestamp + ".bak")
    backup_path.parent.mkdir(parents=True, exist_ok=True)

    shutil.copy2(path, backup_path)

    temporary = path.with_name(path.name + ".pyforge_tmp")

    try:
        with temporary.open("x", encoding="utf-8") as file:
            file.write(content)

        temporary.replace(path)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise

    return {
        "success": True,
        "path": relative.as_posix(),
        "backup": str(backup_path.relative_to(BASE_DIR)),
        "message": "File saved and previous version backed up."
    }


# PYFORGE_FILES_STUDIO_OPERATIONS_V1

def rename_item(name, relative_path, new_name):
    root, path = safe_file_path(name, relative_path)
    if not path.exists():
        raise FileNotFoundError("Item not found.")

    new_name = validate_new_name(new_name)
    target = path.with_name(new_name)

    if target == path:
        return {"success": True, "path": path.relative_to(root).as_posix()}

    if target.exists() or target.is_symlink():
        raise FileExistsError("An item with that name already exists.")

    path.rename(target)
    return {
        "success": True,
        "old_path": relative_path,
        "path": target.relative_to(root).as_posix(),
        "message": "Item renamed successfully."
    }


def duplicate_file(name, relative_path, new_name):
    root, path = safe_file_path(name, relative_path)
    if not path.is_file():
        raise FileNotFoundError("File not found.")

    new_name = validate_new_name(new_name)
    target = path.with_name(new_name)

    if target.exists() or target.is_symlink():
        raise FileExistsError("An item with that name already exists.")

    shutil.copy2(path, target)
    return {
        "success": True,
        "path": target.relative_to(root).as_posix(),
        "message": "File duplicated successfully."
    }


def _check_deletable_tree(folder):
    for item in folder.iterdir():
        if item.is_symlink():
            raise ValueError("Cannot delete a folder containing symbolic links.")
        if item.name in IGNORED and item.is_dir():
            raise ValueError("Cannot delete a folder containing protected directories.")
        if item.is_dir():
            _check_deletable_tree(item)


def delete_item(name, relative_path):
    root, path = safe_file_path(name, relative_path)
    if not path.exists():
        raise FileNotFoundError("Item not found.")

    if path.is_dir():
        _check_deletable_tree(path)
        shutil.rmtree(path)
    else:
        path.unlink()

    return {
        "success": True,
        "path": relative_path,
        "message": "Item deleted successfully."
    }


def create_project_zip(name):
    import io
    import os
    import zipfile

    root = project_root(name)
    output = io.BytesIO()

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for current, directories, files in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)

            directories[:] = [
                directory for directory in directories
                if directory not in IGNORED
                and not (current_path / directory).is_symlink()
            ]

            for filename in files:
                file_path = current_path / filename
                if file_path.is_symlink() or not file_path.is_file():
                    continue

                archive_name = (Path(name) / file_path.relative_to(root)).as_posix()
                archive.write(file_path, archive_name)

    output.seek(0)
    return output
