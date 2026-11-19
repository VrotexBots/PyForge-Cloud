#!/data/data/com.termux/files/usr/bin/bash

cd "$HOME/PyForge" || exit 1

mkdir -p logs runtime

echo "Supervisor started: $(date)" >> logs/boot-server.log

while true; do

    if ! pgrep -f '[u]vicorn main:app' >/dev/null; then
        echo "Starting API: $(date)" >> logs/boot-server.log

        cd "$HOME/PyForge"
        nohup python -m uvicorn main:app \
            --host 0.0.0.0 \
            --port 8001 \
            >> logs/api-server.log 2>&1 &
    fi

    if ! pgrep -f '[p]ython -m http.server 8002' >/dev/null; then
        echo "Starting dashboard: $(date)" >> logs/boot-server.log

        cd "$HOME/PyForge/dashboard_v2"
        nohup python -m http.server 8002 \
            --bind 0.0.0.0 \
            >> "$HOME/PyForge/logs/dashboard-server.log" 2>&1 &
    fi

    sleep 15
done
