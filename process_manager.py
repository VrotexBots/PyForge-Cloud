import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from configuration.config import LOGS_DIR
from projects.file_manager import safe_file_path

LOG_DIR = LOGS_DIR / "console"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_lock = threading.RLock()

_state = {
    "process": None,
    "run_id": None,
    "project": None,
    "script": None,
    "status": "not_yet",
    "started_at": None,
    "ended_at": None,
    "started_monotonic": None,
    "runtime_seconds": 0.0,
    "return_code": None,
    "stop_requested": False,
    "output": deque(maxlen=2000),
    "log_path": None,
    "log_handle": None,
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _write_locked(message, level="INFO", handle=None, run_id=None):
    stamp = _now()
    line = f"[{stamp}] [{level}] {message}"

    target = handle or _state.get("log_handle")
    if target:
        try:
            target.write(line + "\n")
            target.flush()
        except OSError:
            pass

    if run_id is None or _state["run_id"] == run_id:
        _state["output"].append(line)

    return line


def _resolve_entrypoint(project, script=None):
    if script:
        root, path = safe_file_path(project, script)
        if not path.is_file():
            raise FileNotFoundError(f"Python file not found: {script}")
        if path.suffix.lower() != ".py":
            raise ValueError("Only Python (.py) files can be run.")
        return root, path

    for candidate in ("main.py", "app.py", "bot.py"):
        root, path = safe_file_path(project, candidate)
        if path.is_file():
            return root, path

    root, _ = safe_file_path(project, "entrypoint-check.py")
    candidates = sorted(
        path for path in root.glob("*.py")
        if path.is_file() and not path.is_symlink()
    )

    if len(candidates) == 1:
        return root, candidates[0]

    if not candidates:
        raise FileNotFoundError(
            "No main.py, app.py, bot.py or other top-level Python file was found."
        )

    names = ", ".join(path.name for path in candidates)
    raise ValueError(
        "No standard entry point was found. Multiple Python files exist: "
        + names + ". Add main.py or choose an entry point."
    )


def _refresh_locked():
    process = _state["process"]
    if process is None or _state["status"] != "running":
        return

    return_code = process.poll()
    if return_code is None:
        return

    started = _state["started_monotonic"]
    if started is not None:
        _state["runtime_seconds"] = round(time.monotonic() - started, 2)

    _state["ended_at"] = _now()
    _state["return_code"] = return_code
    _state["status"] = (
        "stopped"
        if return_code == 0 or _state["stop_requested"]
        else "error"
    )

    _write_locked(
        f"Process ended. Status={_state['status']}; exit code={return_code}; "
        f"runtime={_state['runtime_seconds']} seconds.",
        "INFO" if _state["status"] == "stopped" else "ERROR",
    )


def _snapshot_locked():
    _refresh_locked()

    elapsed = _state["runtime_seconds"]
    if _state["status"] == "running" and _state["started_monotonic"] is not None:
        elapsed = time.monotonic() - _state["started_monotonic"]

    run_id = _state["run_id"]
    return {
        "run_id": run_id,
        "project": _state["project"],
        "script": _state["script"],
        "status": _state["status"],
        "started_at": _state["started_at"],
        "ended_at": _state["ended_at"],
        "runtime_seconds": round(elapsed, 2),
        "return_code": _state["return_code"],
        "output": list(_state["output"]),
        "log_url": f"/api/console/logs/{run_id}" if run_id else None,
    }


def _read_output(process, run_id, handle):
    try:
        for raw_line in iter(process.stdout.readline, ""):
            line = raw_line.rstrip("\r\n")
            with _lock:
                _write_locked(line, "OUTPUT", handle=handle, run_id=run_id)
    finally:
        if process.stdout:
            process.stdout.close()

        with _lock:
            if _state["run_id"] == run_id:
                _refresh_locked()

        try:
            handle.flush()
            handle.close()
        except OSError:
            pass


def get_status():
    with _lock:
        return _snapshot_locked()


def start_process(project, script=None):
    with _lock:
        _refresh_locked()

        if _state["status"] == "running":
            raise RuntimeError("A project is already running. End it first.")

        run_id = uuid4().hex
        log_path = LOG_DIR / f"{run_id}.log"
        handle = log_path.open("a", encoding="utf-8", buffering=1)

        _state.update({
            "process": None,
            "run_id": run_id,
            "project": project,
            "script": script,
            "status": "starting",
            "started_at": _now(),
            "ended_at": None,
            "started_monotonic": None,
            "runtime_seconds": 0.0,
            "return_code": None,
            "stop_requested": False,
            "output": deque(maxlen=2000),
            "log_path": log_path,
            "log_handle": handle,
        })

        _write_locked("========================================", handle=handle)
        _write_locked("PYFORGE PROJECT START REQUESTED", handle=handle)
        _write_locked(f"Project: {project}", handle=handle)
        _write_locked(f"Run ID: {run_id}", handle=handle)
        _write_locked("Detecting project entry point...", handle=handle)

        try:
            root, path = _resolve_entrypoint(project, script)
            relative_script = path.relative_to(root).as_posix()
            _state["script"] = relative_script

            _write_locked(f"Detected entry point: {relative_script}", handle=handle)
            _write_locked(f"Working directory: {root}", handle=handle)
            _write_locked(f"Python executable: {sys.executable}", handle=handle)
            _write_locked("Launching Python process...", handle=handle)

            process = subprocess.Popen(
                [sys.executable, "-u", str(path)],
                cwd=str(root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                start_new_session=True,
            )

            _state["process"] = process
            _state["status"] = "running"
            _state["started_monotonic"] = time.monotonic()
            _write_locked(f"Process started successfully. PID={process.pid}", handle=handle)

            reader = threading.Thread(
                target=_read_output,
                args=(process, run_id, handle),
                daemon=True,
            )
            reader.start()

        except Exception as error:
            _state["status"] = "error"
            _state["ended_at"] = _now()
            _state["return_code"] = None
            _write_locked(
                f"STARTUP FAILED: {type(error).__name__}: {error}",
                "ERROR",
                handle=handle,
            )
            _write_locked("See this log for the startup diagnostic.", "ERROR", handle=handle)
            handle.flush()
            handle.close()
            if _state["log_handle"] is handle:
                _state["log_handle"] = None

        return _snapshot_locked()


def stop_process():
    with _lock:
        _refresh_locked()
        process = _state["process"]

        if process is None or _state["status"] != "running":
            _write_locked("END requested, but no process is currently running.", "WARNING")
            return _snapshot_locked()

        _state["stop_requested"] = True
        _write_locked("END requested. Sending termination signal...", "WARNING")

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.terminate()
        except OSError:
            pass

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _write_locked("Process did not stop in time. Sending force-kill signal.", "WARNING")
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                process.kill()
            except OSError:
                pass
        process.wait(timeout=3)

    with _lock:
        _refresh_locked()
        return _snapshot_locked()


def restart_process(project, script=None):
    stop_process()
    return start_process(project, script)


def get_log_file(run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise FileNotFoundError("Invalid log ID.")

    path = (LOG_DIR / f"{run_id}.log").resolve()
    if path.parent != LOG_DIR.resolve() or not path.is_file():
        raise FileNotFoundError("The requested log file was not found.")

    return path
