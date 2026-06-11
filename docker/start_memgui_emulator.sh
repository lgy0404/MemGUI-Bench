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
TIMEOUT="${EMULATOR_TIMEOUT:-1200}"
BOOT_SNAPSHOT="${MEMGUI_BOOT_SNAPSHOT:-}"
INIT_SNAPSHOT="${MEMGUI_INIT_SNAPSHOT:-}"
DEVICE_ID="emulator-${CONSOLE_PORT}"
AVD_DIR="${ANDROID_SDK_ROOT}/avd/${AVD_NAME}.avd"

disable_avd_modem() {
  local avd_file
  for avd_file in "${AVD_DIR}/config.ini" "${AVD_DIR}/hardware-qemu.ini"; do
    if [ ! -f "${avd_file}" ]; then
      continue
    fi
    if grep -q '^hw\.gsmModem' "${avd_file}"; then
      sed -i 's/^hw\.gsmModem.*/hw.gsmModem = false/' "${avd_file}"
    else
      printf '\nhw.gsmModem = false\n' >> "${avd_file}"
    fi
  done
}

preauthorize_adb_key() {
  local adb_public_key="${ADB_VENDOR_KEYS}.pub"
  local adb_dir="${AVD_DIR}/data/misc/adb"
  local adb_keys="${adb_dir}/adb_keys"

  if [ ! -f "${adb_public_key}" ]; then
    echo "ADB public key not found at ${adb_public_key}; falling back to UI authorization"
    return
  fi

  mkdir -p "${adb_dir}"
  cp "${adb_public_key}" "${adb_keys}"
  chmod 700 "${adb_dir}" || true
  chmod 640 "${adb_keys}" || true
  echo "Pre-authorized ADB key at ${adb_keys}"
}

activate_adb_keyboard() {
  local package="com.android.adbkeyboard"
  local ime="com.android.adbkeyboard/.AdbIME"
  local current_ime

  if adb -s "${DEVICE_ID}" shell pm list packages "${package}" 2>/dev/null | grep -F -q "${package}"; then
    adb -s "${DEVICE_ID}" shell ime enable "${ime}" || true
    adb -s "${DEVICE_ID}" shell ime set "${ime}" || true
    current_ime="$(adb -s "${DEVICE_ID}" shell settings get secure default_input_method 2>/dev/null | tr -d '\r' || true)"
    echo "Default input method: ${current_ime:-<empty>}"
  else
    echo "ADB Keyboard is not installed; runtime will fall back to adb shell input text"
  fi
}

adb devices | awk '/emulator/ {print $1}' | xargs -r -I {} adb -s "{}" emu kill || true
adb kill-server >/dev/null 2>&1 || true
adb start-server >/dev/null
disable_avd_modem
preauthorize_adb_key

options=(
  "@${EMULATOR_NAME}"
  -no-window
  -no-boot-anim
  -no-audio
  -no-metrics
  -memory "${MEMORY}"
  -ports "${CONSOLE_PORT},${ADB_PORT}"
  -grpc "${GRPC_PORT}"
  -skip-adb-auth
  -gpu swiftshader_indirect
)

if [ -n "${BOOT_SNAPSHOT}" ] && [ "${BOOT_SNAPSHOT}" != "none" ] && [ "${BOOT_SNAPSHOT}" != "false" ]; then
  options+=(-snapshot "${BOOT_SNAPSHOT}" -no-snapshot-save)
else
  options+=(-no-snapshot-load -no-snapshot-save)
fi

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
    activate_adb_keyboard
    if [ -n "${INIT_SNAPSHOT}" ] && [ "${INIT_SNAPSHOT}" != "none" ] && [ "${INIT_SNAPSHOT}" != "false" ]; then
      echo "Saving MemGUI init snapshot: ${INIT_SNAPSHOT}"
      adb -s "${DEVICE_ID}" emu avd snapshot delete "${INIT_SNAPSHOT}" >/dev/null 2>&1 || true
      adb -s "${DEVICE_ID}" emu avd snapshot save "${INIT_SNAPSHOT}"
    fi
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
