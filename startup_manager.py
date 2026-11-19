from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone
from pathlib import Path
import os
import signal
import subprocess
import threading
import urllib.request
import json
from collections import deque

router = APIRouter(tags=["Startup Manager"])

BASE_DIR = Path.home() / "PyForge"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

EVENT_LOG = LOG_DIR / "startup-manager.log"

EVENTS = deque(maxlen=30)
EVENT_LOCK = threading.Lock()
WAKE_LOCK_REQUESTED = False


def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def record_event(message):
    event = {"time": now(), "message": message}

    with EVENT_LOCK:
        EVENTS.appendleft(event)

    try:
        with EVENT_LOG.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event) + "\n")
    except OSError:
        pass


def get_pids(pattern):
    try:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True,
            text=True,
            timeout=3
        )

        return [
            int(line.strip())
            for line in result.stdout.splitlines()
            if line.strip().isdigit()
        ]
    except Exception:
        return []


def check_url(url):
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "PyForge-Startup-Manager"}
        )

        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status == 200
    except Exception:
        return False


def service_status(name, pattern, url=None):
    pids = get_pids(pattern)
    running = bool(pids)

    healthy = check_url(url) if url else running

    return {
        "name": name,
        "running": running,
        "healthy": healthy,
        "pids": pids,
        "pid": pids[0] if pids else None
    }


def get_recent_events():
    with EVENT_LOCK:
        return list(EVENTS)


@router.get("/api/startup/status")
def startup_status():
    services = {
        "api": service_status(
            "PyForge API",
            "[u]vicorn main:app",
            "http://127.0.0.1:8001/api/health"
        ),
        "dashboard": service_status(
            "Dashboard",
            "[p]ython -m http.server 8002",
            "http://127.0.0.1:8002/"
        ),
        "supervisor": service_status(
            "PyForge Supervisor",
            "[p]yforge-supervisor.sh"
        ),
        "backup_guardian": service_status(
            "Backup Guardian",
            "[b]ackup_guardian.py"
        )
    }

    return {
        "ok": True,
        "checked_at": now(),
        "services": services,
        "wake_lock": {
            "requested": WAKE_LOCK_REQUESTED,
            "note": (
                "Wake Lock command was requested. "
                "Android does not expose independent lock verification here."
            )
        },
        "recent_events": get_recent_events()
    }


def stop_service(service):
    if service == "api":
        # The supervisor should relaunch the API after this process exits.
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except ProcessLookupError:
            pass
        return

    if service == "dashboard":
        pids = get_pids("[p]ython -m http.server 8002")

        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


@router.post("/api/startup/restart/{service}")
def restart_service(service: str):
    if service not in ("api", "dashboard"):
        raise HTTPException(
            status_code=400,
            detail="Supported services: api, dashboard"
        )

    supervisor_pids = get_pids("[p]yforge-supervisor.sh")

    if not supervisor_pids:
        raise HTTPException(
            status_code=503,
            detail="Supervisor is not running. Automatic relaunch is unavailable."
        )

    threading.Timer(3.0, stop_service, args=(service,)).start()

    record_event(f"Restart requested for {service}")

    return {
        "ok": True,
        "service": service,
        "message": (
            f"{service} restart requested. "
            "The supervisor should relaunch the service."
        )
    }


@router.post("/api/startup/wake-lock")
def request_wake_lock():
    global WAKE_LOCK_REQUESTED

    executable = "/data/data/com.termux/files/usr/bin/termux-wake-lock"

    if not Path(executable).exists():
        raise HTTPException(
            status_code=503,
            detail="termux-wake-lock was not found."
        )

    try:
        subprocess.Popen(
            [executable],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

        WAKE_LOCK_REQUESTED = True
        record_event("Android wake-lock command requested")

        return {
            "ok": True,
            "message": "Wake-lock command requested successfully."
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Wake-lock request failed: {error}"
        )
