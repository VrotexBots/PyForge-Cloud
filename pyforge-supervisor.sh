#!/data/data/com.termux/files/usr/bin/bash

cd "$HOME/PyForge" || exit 1

mkdir -p logs runtime

LOG="$HOME/PyForge/logs/heartbeat.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"
}

start_api() {
    log "Starting VaultNex/PyForge API..."
    cd "$HOME/PyForge" || return 1

    if [ -f "$HOME/PyForge/runtime/pyforge-secrets.sh" ]; then
        source "$HOME/PyForge/runtime/pyforge-secrets.sh"
    fi

    nohup python -m uvicorn main:app \
        --host 0.0.0.0 \
        --port 8001 \
        >> logs/api-server.log 2>&1 &
}

start_dashboard() {
    log "Starting PyForge dashboard..."
    cd "$HOME/PyForge/dashboard_v2" || return 1

    nohup python -m http.server 8002 \
        --bind 0.0.0.0 \
        >> "$HOME/PyForge/logs/dashboard-server.log" 2>&1 &
}

check_api() {
    if curl -fsS --max-time 5 \
        http://127.0.0.1:8001/api/health >/dev/null 2>&1; then
        return 0
    fi

    log "API heartbeat FAILED. Recovering..."

    for pid in $(pgrep -f '[u]vicorn main:app'); do
        kill "$pid" 2>/dev/null
    done

    sleep 2
    start_api

    for i in $(seq 1 10); do
        sleep 1
        if curl -fsS --max-time 3 \
            http://127.0.0.1:8001/api/health >/dev/null 2>&1; then
            log "API recovered successfully."
            return 0
        fi
    done

    log "WARNING: API still unavailable."
    return 1
}

check_dashboard() {
    if curl -fsS --max-time 5 \
        http://127.0.0.1:8002/ >/dev/null 2>&1; then
        return 0
    fi

    log "Dashboard heartbeat FAILED. Recovering..."

    for pid in $(pgrep -f '[p]ython -m http.server 8002'); do
        kill "$pid" 2>/dev/null
    done

    sleep 2
    start_dashboard

    for i in $(seq 1 10); do
        sleep 1
        if curl -fsS --max-time 3 \
            http://127.0.0.1:8002/ >/dev/null 2>&1; then
            log "Dashboard recovered successfully."
            return 0
        fi
    done

    log "WARNING: Dashboard still unavailable."
    return 1
}

log "======================================"
log "PYFORGE HEARTBEAT SUPERVISOR STARTED"
log "======================================"

while true; do

    check_api
    check_dashboard

    if ! pgrep -f '[b]ackup_guardian.py' >/dev/null; then
        log "Backup Guardian missing. Restarting..."
        cd "$HOME/PyForge" || exit 1
        nohup python runtime/backup_guardian.py \
            >> logs/backup-guardian-process.log 2>&1 &
    fi

    log "Heartbeat cycle completed."
    sleep 15

done
