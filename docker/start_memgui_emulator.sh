#!/bin/bash
set -euo pipefail

export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-/root/.android}"
export ANDROID_HOME="${ANDROID_HOME:-$ANDROID_SDK_ROOT}"
export AVD_NAME="${AVD_NAME:-MemGUI-AVD-250704}"
export EMULATOR_NAME="${EMULATOR_NAME:-$AVD_NAME}"
export PATH="/root/.local/bin:${ANDROID_SDK_ROOT}/emulator:${ANDROID_SDK_ROOT}/tools:${ANDROID_SDK_ROOT}/tools/bin:${ANDROID_SDK_ROOT}/platform-tools:${PATH}"
export ADB_VENDOR_KEYS="${ADB_VENDOR_KEYS:-/root/.android/adbkey}"

CONSOLE_PORT="${EMULATOR_CONSOLE_PORT:-5554}"
ADB_PORT="${EMULATOR_ADB_PORT:-5555}"
GRPC_PORT="${EMULATOR_GRPC_PORT:-8554}"
MEMORY="${EMULATOR_MEMORY:-2048}"
TIMEOUT="${EMULATOR_TIMEOUT:-600}"
DEVICE_ID="emulator-${CONSOLE_PORT}"

adb devices | awk '/emulator/ {print $1}' | xargs -r -I {} adb -s "{}" emu kill || true
adb kill-server >/dev/null 2>&1 || true
adb start-server >/dev/null

options=(
  "@${EMULATOR_NAME}"
  -no-window
  -no-snapshot
  -no-boot-anim
  -no-audio
  -no-metrics
  -memory "${MEMORY}"
  -ports "${CONSOLE_PORT},${ADB_PORT}"
  -grpc "${GRPC_PORT}"
  -skip-adb-auth
  -gpu swiftshader_indirect
)

if grep -E -q '(vmx|svm)' /proc/cpuinfo; then
  options+=(-accel on)
else
  options+=(-accel off)
fi

echo "Starting MemGUI emulator: emulator ${options[*]}"
nohup emulator "${options[@]}" >/tmp/memgui-emulator.nohup 2>&1 &

if [ "${AUTO_AUTHORIZE_ADB:-true}" != "false" ] && [ "${AUTO_AUTHORIZE_ADB:-true}" != "0" ]; then
  (
    cd /app/service
    .venv/bin/python /app/docker/authorize_adb_grpc.py \
      --device "${DEVICE_ID}" \
      --grpc-port "${GRPC_PORT}" \
      --timeout "${TIMEOUT}" \
      --tap-always-allow
  ) >> /var/log/adb-auth.log 2>&1 &
fi

start_time="$(date +%s)"
spinner=( "..." "...." "....." )
i=0
while true; do
  state="$(adb -s "${DEVICE_ID}" get-state 2>&1 || true)"
  boot_completed="$(adb -s "${DEVICE_ID}" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)"

  if [ "${boot_completed}" = "1" ]; then
    echo "Emulator is ready: ${DEVICE_ID}"
    adb -s "${DEVICE_ID}" shell input keyevent 82 || true
    adb -s "${DEVICE_ID}" shell "settings put global window_animation_scale 0.0" || true
    adb -s "${DEVICE_ID}" shell "settings put global transition_animation_scale 0.0" || true
    adb -s "${DEVICE_ID}" shell "settings put global animator_duration_scale 0.0" || true
    adb -s "${DEVICE_ID}" shell "settings put global hidden_api_policy_pre_p_apps 1; settings put global hidden_api_policy_p_apps 1; settings put global hidden_api_policy 1" || true
    adb -s "${DEVICE_ID}" root || true
    adb devices -l
    exit 0
  fi

  elapsed="$(( $(date +%s) - start_time ))"
  if [ "${elapsed}" -gt "${TIMEOUT}" ]; then
    echo "Timeout waiting for emulator after ${TIMEOUT}s"
    echo "Last adb state: ${state}"
    echo "--- emulator nohup tail ---"
    tail -120 /tmp/memgui-emulator.nohup 2>/dev/null || true
    echo "--- adb auth tail ---"
    tail -120 /var/log/adb-auth.log 2>/dev/null || true
    exit 1
  fi

  echo "Waiting for ${DEVICE_ID}: state=${state}, boot=${boot_completed:-<empty>} ${spinner[$((i % 3))]}"
  i="$((i + 1))"
  sleep 4
done
