#!/bin/bash
set -euo pipefail

export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-/root/.android}"
export ANDROID_HOME="${ANDROID_HOME:-$ANDROID_SDK_ROOT}"
export AVD_NAME="${AVD_NAME:-MemGUI-AVD-250704}"
export EMULATOR_NAME="${EMULATOR_NAME:-$AVD_NAME}"
export PATH="/root/.local/bin:${ANDROID_SDK_ROOT}/emulator:${ANDROID_SDK_ROOT}/tools:${ANDROID_SDK_ROOT}/tools/bin:${ANDROID_SDK_ROOT}/platform-tools:${PATH}"

mkdir -p /app/docker /app/service /var/log
touch \
    /var/log/emulator.log \
    /var/log/server.log \
    /var/log/adb-auth.log \
    /var/log/adb-relay.log \
    /var/log/viewer.log

find /root/.android/avd/ -name '*.lock' -type f -delete 2>/dev/null || true

if [ "${ENABLE_VIEWER:-false}" = "true" ] || [ "${ENABLE_VIEWER:-false}" = "1" ]; then
    cd /app/service
    uv run python /app/docker/ws_adb_proxy.py \
        --adb-port 5555 --port 7860 --static /app/web-scrcpy \
        >> /var/log/viewer.log 2>&1 &
fi

bash /app/docker/start_memgui_emulator.sh >> /var/log/emulator.log 2>&1

python3 /app/docker/adb_tcp_relay.py \
    --listen-host 0.0.0.0 --listen-port 5556 \
    --target-host 127.0.0.1 --target-port 5555 \
    >> /var/log/adb-relay.log 2>&1 &

cd /app/service
uv run mg server --port 6800 >> /var/log/server.log 2>&1 &

exec "$@"
