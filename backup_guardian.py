import os
import sys
import time
import fcntl
import traceback
from datetime import datetime, timezone
from pathlib import Path

BASE = Path.home() / "PyForge"
sys.path.insert(0, str(BASE))
LOG_DIR = BASE / "logs"
RUNTIME_DIR = BASE / "runtime"

LOG_DIR.mkdir(parents=True, exist_ok=True)
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "backup-guardian.log"
LOCK_FILE = RUNTIME_DIR / "backup-guardian.lock"

INTERVAL_SECONDS = 6 * 60 * 60


def log(message):
    timestamp = datetime.now(timezone.utc).isoformat()
    with LOG_FILE.open("a", encoding="utf-8") as file:
        file.write(f"[{timestamp}] {message}\n")
        file.flush()


def main():
    os.chdir(BASE)

    # Prevent two Guardian instances from running together.
    lock = LOCK_FILE.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("Another Guardian instance already holds the lock. Exiting.")
        return

    from backup_factory.engine import create_backup, verify_backup

    log("Backup Guardian started.")
    log("Automatic backup interval: 6 hours.")
    log("Existing backups will not be automatically deleted.")

    first_backup = True

    while True:
        try:
            if first_backup:
                log("First backup starting immediately after Guardian startup.")
                first_backup = False
            else:
                log("Waiting six hours until the next scheduled backup.")
                time.sleep(INTERVAL_SECONDS)

            log("Scheduled backup starting.")

            backup = create_backup()
            filename = backup["filename"]

            log(
                f"Backup created: {filename}; "
                f"files: {backup.get('files_count', 'unknown')}"
            )

            result = verify_backup(filename)

            if result.get("verified") is True:
                log(
                    f"VERIFIED: {filename}; "
                    f"SHA256: {result.get('sha256', 'not reported')}"
                )
            else:
                log(f"VERIFICATION FAILED: {filename}")

        except Exception:
            log("BACKUP ERROR:\n" + traceback.format_exc())


if __name__ == "__main__":
    main()
