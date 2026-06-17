#!/bin/bash
set -euo pipefail

export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-/root/.android}"
export ANDROID_HOME="${ANDROID_HOME:-$ANDROID_SDK_ROOT}"
export AVD_NAME="${AVD_NAME:-MemGUI-AVD-260614}"
export EMULATOR_NAME="${EMULATOR_NAME:-$AVD_NAME}"
export PATH="/root/.local/bin:${ANDROID_SDK_ROOT}/emulator:${ANDROID_SDK_ROOT}/tools:${ANDROID_SDK_ROOT}/tools/bin:${ANDROID_SDK_ROOT}/platform-tools:${PATH}"
PYTHON_BIN="${PYTHON_BIN:-/app/service/.venv/bin/python}"
MG_BIN="${MG_BIN:-/app/service/.venv/bin/mg}"

PROXY="${http_proxy:-${HTTP_PROXY:-}}"
HTTPS_PROXY_VALUE="${https_proxy:-${HTTPS_PROXY:-${PROXY}}}"
USER_NO_PROXY="${no_proxy:-${NO_PROXY:-}}"
DEFAULT_NO_PROXY="10.0.2.2,127.0.0.1,localhost,::1"

if [ -n "${PROXY}" ]; then
    export http_proxy="${PROXY}"
    export HTTP_PROXY="${PROXY}"
fi
if [ -n "${HTTPS_PROXY_VALUE}" ]; then
    export https_proxy="${HTTPS_PROXY_VALUE}"
    export HTTPS_PROXY="${HTTPS_PROXY_VALUE}"
fi
if [ -n "${PROXY}${HTTPS_PROXY_VALUE}${USER_NO_PROXY}" ]; then
    export no_proxy="${DEFAULT_NO_PROXY}${USER_NO_PROXY:+,${USER_NO_PROXY}}"
    export NO_PROXY="${no_proxy}"
    echo "INFO: outbound HTTP proxy = ${PROXY:-<none>} (HTTPS=${HTTPS_PROXY_VALUE:-<none>}, NO_PROXY=${NO_PROXY})"
fi

if [ ! -x "${PYTHON_BIN}" ]; then
    PYTHON_BIN="$(command -v python3 || true)"
fi
if [ ! -x "${MG_BIN}" ]; then
    MG_BIN="$(command -v mg || true)"
fi
if [ -z "${PYTHON_BIN}" ] || [ -z "${MG_BIN}" ]; then
    echo "Unable to find Python or mg executable in the runtime image" >&2
    exit 127
fi

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
    "${PYTHON_BIN}" /app/docker/ws_adb_proxy.py \
        --adb-port 5555 --port 7860 --static /app/web-scrcpy \
        >> /var/log/viewer.log 2>&1 &
fi

bash /app/docker/start_memgui_emulator.sh >> /var/log/emulator.log 2>&1

"${PYTHON_BIN}" /app/docker/adb_tcp_relay.py \
    --listen-host 0.0.0.0 --listen-port 5556 \
    --target-host 127.0.0.1 --target-port 5555 \
    >> /var/log/adb-relay.log 2>&1 &

cd /app/service
"${MG_BIN}" server --port 6800 >> /var/log/server.log 2>&1 &

exec "$@"
